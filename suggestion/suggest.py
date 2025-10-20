import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
from datetime import datetime
import os
from typing import Optional

ADMIN_ID = 252130669919076352

class DenyModal(discord.ui.Modal, title="Reason for denying suggestion"):
    reason = discord.ui.TextInput(label="Reason (optional)", style=discord.TextStyle.long, required=False, max_length=2000)

    def __init__(self, suggestion_id: int, user_id: int, suggestion_text: str, channel_id: int, admin_message_id: Optional[int], bot: commands.Bot):
        super().__init__()
        self.suggestion_id = suggestion_id
        self.user_id = user_id
        self.suggestion_text = suggestion_text
        self.channel_id = channel_id
        self.admin_message_id = admin_message_id
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        reason_text = self.reason.value or None

        db_path = os.path.join(os.path.dirname(__file__), "suggestions.db")
        async with aiosqlite.connect(db_path) as db:
            await db.execute("UPDATE suggestions SET status = ?, reason = ? WHERE id = ?", ("Denied", reason_text, self.suggestion_id))
            await db.commit()

        # Respond to modal submit
        await interaction.response.send_message(f"❌ Suggestion #{self.suggestion_id} denied.", ephemeral=False)

        # Notify user
        try:
            user = await self.bot.fetch_user(self.user_id)
            dm_note = f"❌ Your suggestion (ID: {self.suggestion_id}) — `{self.suggestion_text}` has been **denied**."
            if reason_text:
                dm_note += f"\n**Reason:** {reason_text}"
            await user.send(dm_note)
        except:
            pass

        # Notify original channel
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            try:
                msg = f"❌ Suggestion **#{self.suggestion_id}** (`{self.suggestion_text}`) has been **denied**."
                if reason_text:
                    msg += f"\n**Reason:** {reason_text}"
                await channel.send(msg)
            except:
                pass

        # Disable buttons on admin message (if we have the message id)
        if self.admin_message_id:
            try:
                admin_user = await self.bot.fetch_user(ADMIN_ID)
                dm = admin_user.dm_channel or await admin_user.create_dm()
                orig_msg = await dm.fetch_message(self.admin_message_id)
                # Create a view with same custom_ids but disabled
                disabled_view = SuggestionButtons(self.bot, suggestion_id=self.suggestion_id, user_id=self.user_id, suggestion_text=self.suggestion_text, channel_id=self.channel_id, admin_message_id=self.admin_message_id, disabled=True)
                await orig_msg.edit(view=disabled_view)
            except Exception:
                pass


class SuggestionButtons(discord.ui.View):
    def __init__(self, bot, suggestion_id=None, user_id=None, suggestion_text=None, channel_id=None, admin_message_id: Optional[int]=None, disabled: bool=False):
        # timeout=None to make persistent
        super().__init__(timeout=None)
        self.bot = bot
        self.suggestion_id = suggestion_id
        self.user_id = user_id
        self.suggestion_text = suggestion_text
        self.channel_id = channel_id
        self.admin_message_id = admin_message_id

        # custom_id includes message id so callbacks can find the message later; message id may be None for re-registering but that's fine
        approve_cid = f"suggest_approve_{suggestion_id}_{admin_message_id or 0}"
        deny_cid = f"suggest_deny_{suggestion_id}_{admin_message_id or 0}"

        approve_btn = discord.ui.Button(
            label="Approve ✅",
            style=discord.ButtonStyle.success,
            custom_id=approve_cid
        )
        approve_btn.callback = self.approve
        approve_btn.disabled = disabled
        self.add_item(approve_btn)

        deny_btn = discord.ui.Button(
            label="Deny ❌",
            style=discord.ButtonStyle.danger,
            custom_id=deny_cid
        )
        deny_btn.callback = self.deny
        deny_btn.disabled = disabled
        self.add_item(deny_btn)

    async def approve(self, interaction: discord.Interaction):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message("❌ You can't approve suggestions.", ephemeral=True)
            return

        if not self.suggestion_id:
            await interaction.response.send_message("⚠️ This button is no longer active.", ephemeral=True)
            return

        db_path = os.path.join(os.path.dirname(__file__), "suggestions.db")
        async with aiosqlite.connect(db_path) as db:
            await db.execute("UPDATE suggestions SET status = ? WHERE id = ?", ("Approved", self.suggestion_id))
            await db.commit()

        await interaction.response.send_message(f"✅ Suggestion #{self.suggestion_id} approved.", ephemeral=False)

        # Notify user
        try:
            user = await self.bot.fetch_user(self.user_id)
            await user.send(f"✅ Your suggestion (ID: {self.suggestion_id}) — `{self.suggestion_text}` has been **approved!**")
        except:
            pass

        # Notify original channel
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            await channel.send(f"✅ Suggestion **#{self.suggestion_id}** (`{self.suggestion_text}`) has been **approved!**")

        # Disable buttons after action by editing the admin message (if present)
        if self.admin_message_id:
            try:
                admin_user = await self.bot.fetch_user(ADMIN_ID)
                dm = admin_user.dm_channel or await admin_user.create_dm()
                orig_msg = await dm.fetch_message(self.admin_message_id)
                disabled_view = SuggestionButtons(self.bot, suggestion_id=self.suggestion_id, user_id=self.user_id, suggestion_text=self.suggestion_text, channel_id=self.channel_id, admin_message_id=self.admin_message_id, disabled=True)
                await orig_msg.edit(view=disabled_view)
            except Exception:
                # fallback: try to disable children of THIS view and edit message (if interaction.message exists)
                for item in self.children:
                    item.disabled = True
                try:
                    await interaction.message.edit(view=self)
                except:
                    pass

    async def deny(self, interaction: discord.Interaction):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message("❌ You can't deny suggestions.", ephemeral=True)
            return

        if not self.suggestion_id:
            await interaction.response.send_message("⚠️ This button is no longer active.", ephemeral=True)
            return

        # Show a modal to capture reason
        modal = DenyModal(suggestion_id=self.suggestion_id, user_id=self.user_id, suggestion_text=self.suggestion_text, channel_id=self.channel_id, admin_message_id=self.admin_message_id, bot=self.bot)
        await interaction.response.send_modal(modal)


class Suggestion(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = os.path.join(os.path.dirname(__file__), "suggestions.db")
        self.db = None

    async def cog_load(self):
        # Connect to database and ensure schema (including reason and admin_message_id)
        self.db = await aiosqlite.connect(self.db_path)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                suggestion TEXT,
                status TEXT,
                channel_id INTEGER,
                reason TEXT,
                admin_message_id INTEGER
            )
        """)
        await self.db.commit()

        # Register persistent views for pending suggestions so buttons keep working after restarts.
        async with self.db.execute("SELECT id, user_id, suggestion, channel_id, admin_message_id FROM suggestions WHERE status = ?", ("Pending",)) as cursor:
            rows = await cursor.fetchall()

        for sid, uid, suggestion_text, channel_id, admin_msg_id in rows:
            # Only re-register views if we have an admin_message_id (message was sent)
            # but even if admin_msg_id is None, we register a view with admin_message_id None -> custom_id uses 0
            v = SuggestionButtons(self.bot, suggestion_id=sid, user_id=uid, suggestion_text=suggestion_text, channel_id=channel_id, admin_message_id=admin_msg_id)
            try:
                # registers the view for persistent components handling
                self.bot.add_view(v)
            except Exception:
                pass

    async def cog_unload(self):
        if self.db:
            await self.db.close()

    @app_commands.command(name="suggest", description="Submit a suggestion")
    async def suggest(self, interaction: discord.Interaction, idea: str):
        try:
            # Insert suggestion into DB
            await self.db.execute(
                "INSERT INTO suggestions (user_id, suggestion, status, channel_id) VALUES (?, ?, ?, ?)",
                (interaction.user.id, idea, "Pending", interaction.channel_id)
            )
            await self.db.commit()

            async with self.db.execute("SELECT last_insert_rowid()") as cursor:
                suggestion_id = (await cursor.fetchone())[0]

            await interaction.response.send_message(
                f"✅ Suggestion submitted! (ID: **{suggestion_id}**)\n> {idea}"
            )

            # Send DM to admin with persistent buttons
            try:
                admin = await self.bot.fetch_user(ADMIN_ID)
                embed = discord.Embed(
                    title=f"New Suggestion (ID: {suggestion_id})",
                    description=idea,
                    color=discord.Color.blurple(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Suggested by", value=f"{interaction.user} ({interaction.user.id})")
                embed.add_field(name="Channel", value=f"<#{interaction.channel_id}>")

                view = SuggestionButtons(self.bot, suggestion_id, interaction.user.id, idea, interaction.channel_id)
                sent = await admin.send(embed=embed, view=view)

                # store admin message id so we can re-register persistent view for it later and edit it
                await self.db.execute("UPDATE suggestions SET admin_message_id = ? WHERE id = ?", (sent.id, suggestion_id))
                await self.db.commit()

                # Register the view so the component interactions will be handled (persistent)
                try:
                    self.bot.add_view(SuggestionButtons(self.bot, suggestion_id, interaction.user.id, idea, interaction.channel_id, admin_message_id=sent.id))
                except Exception:
                    pass

            except Exception as e:
                print(f"Failed to send DM to admin: {e}")

        except Exception as e:
            print(f"Error in suggest command: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ An error occurred: {e}", ephemeral=False)
            else:
                await interaction.followup.send(f"❌ An error occurred: {e}", ephemeral=False)

    @app_commands.command(name="suggestion_complete", description="Mark an approved suggestion as completed")
    async def suggestion_complete(self, interaction: discord.Interaction, suggestion_id: int):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message("❌ You don't have permission to do that.", ephemeral=True)
            return

        async with self.db.execute(
            "SELECT user_id, suggestion, status, channel_id FROM suggestions WHERE id = ?", (suggestion_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            await interaction.response.send_message("❌ Suggestion not found.", ephemeral=True)
            return

        user_id, suggestion_text, status, channel_id = row
        if status != "Approved":
            await interaction.response.send_message("⚠️ This suggestion must be approved before marking as complete.", ephemeral=True)
            return

        await self.db.execute("UPDATE suggestions SET status = ? WHERE id = ?", ("Completed", suggestion_id))
        await self.db.commit()

        await interaction.response.send_message(f"✅ Suggestion #{suggestion_id} marked as completed!", ephemeral=False)

        # Notify user
        try:
            user = await self.bot.fetch_user(user_id)
            await user.send(f"🎉 Your suggestion (ID: {suggestion_id}) — `{suggestion_text}` has been **implemented!**")
        except:
            pass

        # Notify original channel
        channel = self.bot.get_channel(channel_id)
        if channel:
            await channel.send(f"🎉 Suggestion **#{suggestion_id}** (`{suggestion_text}`) has been marked as **completed!**")

    @app_commands.command(name="suggestion_list", description="List suggestions (use status filter to narrow)")
    @app_commands.choices(status=[
        app_commands.Choice(name="All", value="All"),
        app_commands.Choice(name="Pending", value="Pending"),
        app_commands.Choice(name="Approved", value="Approved"),
        app_commands.Choice(name="Denied", value="Denied"),
        app_commands.Choice(name="Completed", value="Completed")
    ])
    async def suggestion_list(self, interaction: discord.Interaction, status: app_commands.Choice[str]):
        # This command is intentionally not admin-restricted and not ephemeral (per request).
        selected = status.value if status else "All"

        if selected == "All":
            query = "SELECT id, user_id, suggestion, status FROM suggestions ORDER BY id DESC"
            params = ()
        else:
            query = "SELECT id, user_id, suggestion, status FROM suggestions WHERE status = ? ORDER BY id DESC"
            params = (selected,)

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            await interaction.response.send_message("No suggestions found.", ephemeral=False)
            return

        embed = discord.Embed(title=f"📋 Suggestions — {selected}", color=discord.Color.green())
        for sid, uid, suggestion_text, st in rows:
            embed.add_field(
                name=f"ID: {sid} | Status: {st}",
                value=f"<@{uid}> — {suggestion_text[:100]}{'...' if len(suggestion_text) > 100 else ''}",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot):
    await bot.add_cog(Suggestion(bot))
