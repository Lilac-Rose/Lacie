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

        await interaction.response.send_message(f"❌ Suggestion #{self.suggestion_id} denied.", ephemeral=False)

        try:
            user = await self.bot.fetch_user(self.user_id)
            dm_note = f"❌ Your suggestion (ID: {self.suggestion_id}) — `{self.suggestion_text}` has been **denied**."
            if reason_text:
                dm_note += f"\n**Reason:** {reason_text}"
            await user.send(dm_note)
        except:
            pass

        channel = self.bot.get_channel(self.channel_id)
        if channel:
            try:
                msg = f"❌ Suggestion **#{self.suggestion_id}** (`{self.suggestion_text}`) has been **denied**."
                if reason_text:
                    msg += f"\n**Reason:** {reason_text}"
                await channel.send(msg)
            except:
                pass

        if self.admin_message_id:
            try:
                admin_user = await self.bot.fetch_user(ADMIN_ID)
                dm = admin_user.dm_channel or await admin_user.create_dm()
                orig_msg = await dm.fetch_message(self.admin_message_id)
                disabled_view = SuggestionButtons(self.bot, suggestion_id=self.suggestion_id, user_id=self.user_id, suggestion_text=self.suggestion_text, channel_id=self.channel_id, admin_message_id=self.admin_message_id, disabled=True)
                await orig_msg.edit(view=disabled_view)
            except Exception:
                pass


class SuggestionButtons(discord.ui.View):
    def __init__(self, bot, suggestion_id=None, user_id=None, suggestion_text=None, channel_id=None, admin_message_id: Optional[int] = None, disabled: bool = False):
        super().__init__(timeout=None)  # timeout=None makes it persistent
        self.bot = bot
        self.suggestion_id = suggestion_id
        self.user_id = user_id
        self.suggestion_text = suggestion_text
        self.channel_id = channel_id
        self.admin_message_id = admin_message_id

        # Use consistent custom_ids that include the suggestion_id
        approve_cid = f"suggest_approve_{suggestion_id}"
        deny_cid = f"suggest_deny_{suggestion_id}"

        approve_btn = discord.ui.Button(label="Approve ✅", style=discord.ButtonStyle.success, custom_id=approve_cid, disabled=disabled)
        approve_btn.callback = self.approve
        self.add_item(approve_btn)

        deny_btn = discord.ui.Button(label="Deny ❌", style=discord.ButtonStyle.danger, custom_id=deny_cid, disabled=disabled)
        deny_btn.callback = self.deny
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

        try:
            user = await self.bot.fetch_user(self.user_id)
            await user.send(f"✅ Your suggestion (ID: {self.suggestion_id}) — `{self.suggestion_text}` has been **approved!**")
        except:
            pass

        channel = self.bot.get_channel(self.channel_id)
        if channel:
            await channel.send(f"✅ Suggestion **#{self.suggestion_id}** (`{self.suggestion_text}`) has been **approved!**")

        # Disable buttons after approval
        if self.admin_message_id:
            try:
                admin_user = await self.bot.fetch_user(ADMIN_ID)
                dm = admin_user.dm_channel or await admin_user.create_dm()
                orig_msg = await dm.fetch_message(self.admin_message_id)
                disabled_view = SuggestionButtons(self.bot, suggestion_id=self.suggestion_id, user_id=self.user_id, suggestion_text=self.suggestion_text, channel_id=self.channel_id, admin_message_id=self.admin_message_id, disabled=True)
                await orig_msg.edit(view=disabled_view)
            except Exception:
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

        modal = DenyModal(suggestion_id=self.suggestion_id, user_id=self.user_id, suggestion_text=self.suggestion_text, channel_id=self.channel_id, admin_message_id=self.admin_message_id, bot=self.bot)
        await interaction.response.send_modal(modal)


class PaginationView(discord.ui.View):
    def __init__(self, embeds, user: discord.User):
        super().__init__(timeout=180)
        self.embeds = embeds
        self.user = user
        self.current_page = 0

        if len(embeds) == 1:
            self.previous_button.disabled = True
            self.next_button.disabled = True
        else:
            self.previous_button.disabled = True

    async def update_page(self, interaction: discord.Interaction):
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.embeds) - 1
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            await interaction.response.send_message("You can't control this pagination.", ephemeral=True)
            return
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_page(interaction)

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            await interaction.response.send_message("You can't control this pagination.", ephemeral=True)
            return
        if self.current_page < len(self.embeds) - 1:
            self.current_page += 1
            await self.update_page(interaction)


class Suggestion(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = os.path.join(os.path.dirname(__file__), "suggestions.db")
        self.db = None

    async def cog_load(self):
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

        # Re-register persistent views for all pending suggestions
        async with self.db.execute("SELECT id, user_id, suggestion, channel_id, admin_message_id FROM suggestions WHERE status = ?", ("Pending",)) as cursor:
            rows = await cursor.fetchall()

        for sid, uid, suggestion_text, channel_id, admin_msg_id in rows:
            view = SuggestionButtons(
                self.bot, 
                suggestion_id=sid, 
                user_id=uid, 
                suggestion_text=suggestion_text, 
                channel_id=channel_id, 
                admin_message_id=admin_msg_id
            )
            self.bot.add_view(view, message_id=admin_msg_id)
            print(f"Re-registered view for suggestion #{sid} (message {admin_msg_id})")

    async def cog_unload(self):
        if self.db:
            await self.db.close()

    @app_commands.command(name="suggest", description="Submit a suggestion")
    async def suggest(self, interaction: discord.Interaction, idea: str):

        await interaction.response.defer(thinking=True)

        try:
            await self.db.execute(
                "INSERT INTO suggestions (user_id, suggestion, status, channel_id) VALUES (?, ?, ?, ?)",
                (interaction.user.id, idea, "Pending", interaction.channel_id)
            )
            await self.db.commit()

            async with self.db.execute("SELECT last_insert_rowid()") as cursor:
                suggestion_id = (await cursor.fetchone())[0]

            await interaction.followup.send(f"✅ Suggestion submitted! (ID: **{suggestion_id}**)\n> {idea}")

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

                await self.db.execute("UPDATE suggestions SET admin_message_id = ? WHERE id = ?", (sent.id, suggestion_id))
                await self.db.commit()

                # Register the persistent view with the message_id
                persistent_view = SuggestionButtons(
                    self.bot, 
                    suggestion_id, 
                    interaction.user.id, 
                    idea, 
                    interaction.channel_id, 
                    admin_message_id=sent.id
                )
                self.bot.add_view(persistent_view, message_id=sent.id)
                print(f"Registered persistent view for suggestion #{suggestion_id} (message {sent.id})")

            except Exception as e:
                print(f"Failed to send DM to admin: {e}")

        except Exception as e:
            print(f"Error in suggest command: {e}")
            await interaction.followup.send(f"❌ An error occurred: {e}")

    suggestion = app_commands.Group(name="suggestion", description="Manage suggestions")

    @suggestion.command(name="view", description="View full details of a suggestion")
    async def suggestion_view(self, interaction: discord.Interaction, suggestion_id: int):

        await interaction.response.defer(thinking=True)

        async with self.db.execute("SELECT user_id, suggestion, status, channel_id, reason FROM suggestions WHERE id = ?", (suggestion_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            await interaction.followup.send("❌ Suggestion not found.")
            return

        user_id, suggestion_text, status, channel_id, reason = row

        # Create status color mapping
        status_colors = {
            "Pending": discord.Color.yellow(),
            "Approved": discord.Color.green(),
            "Denied": discord.Color.red(),
            "Completed": discord.Color.blue()
        }
        
        embed = discord.Embed(
            title=f"Suggestion #{suggestion_id}",
            description=suggestion_text,
            color=status_colors.get(status, discord.Color.greyple())
        )
        
        try:
            user = await self.bot.fetch_user(user_id)
            embed.add_field(name="Suggested by", value=f"{user.mention} ({user})", inline=True)
        except:
            embed.add_field(name="Suggested by", value=f"<@{user_id}>", inline=True)
        
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Channel", value=f"<#{channel_id}>", inline=True)
        
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        
        await interaction.followup.send(embed=embed)

    @suggestion.command(name="complete", description="Mark an approved suggestion as completed")
    async def suggestion_complete(self, interaction: discord.Interaction, suggestion_id: int):

        await interaction.response.defer(thinking=True)

        if interaction.user.id != ADMIN_ID:
            await interaction.followup.send("❌ You don't have permission to do that.")
            return

        async with self.db.execute("SELECT user_id, suggestion, status, channel_id FROM suggestions WHERE id = ?", (suggestion_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            await interaction.followup.send("❌ Suggestion not found.")
            return

        user_id, suggestion_text, status, channel_id = row
        if status != "Approved":
            await interaction.followup.send("⚠️ This suggestion must be approved before marking as complete.")
            return

        await self.db.execute("UPDATE suggestions SET status = ? WHERE id = ?", ("Completed", suggestion_id))
        await self.db.commit()

        await interaction.followup.send(f"✅ Suggestion #{suggestion_id} marked as completed!")

        try:
            user = await self.bot.fetch_user(user_id)
            await user.send(f"🎉 Your suggestion (ID: {suggestion_id}) — `{suggestion_text}` has been **implemented!**")
        except:
            pass

        channel = self.bot.get_channel(channel_id)
        if channel:
            await channel.send(f"🎉 Suggestion **#{suggestion_id}** (`{suggestion_text}`) has been marked as **completed!**")

    @suggestion.command(name="list", description="List suggestions (use status filter to narrow)")
    @app_commands.choices(status=[
        app_commands.Choice(name="All", value="All"),
        app_commands.Choice(name="Pending", value="Pending"),
        app_commands.Choice(name="Approved", value="Approved"),
        app_commands.Choice(name="Denied", value="Denied"),
        app_commands.Choice(name="Completed", value="Completed")
    ])
    async def suggestion_list(self, interaction: discord.Interaction, status: app_commands.Choice[str]):

        await interaction.response.defer(thinking=True)

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
            await interaction.followup.send("No suggestions found.")
            return

        embeds = []
        per_page = 10
        for i in range(0, len(rows), per_page):
            embed = discord.Embed(title=f"📋 Suggestions — {selected} (Page {i//per_page + 1})", color=discord.Color.green())
            for sid, uid, suggestion_text, st in rows[i:i+per_page]:
                embed.add_field(
                    name=f"ID: {sid} | Status: {st}",
                    value=f"<@{uid}> — {suggestion_text[:100]}{'...' if len(suggestion_text) > 100 else ''}",
                    inline=False
                )
            embeds.append(embed)

        view = PaginationView(embeds, interaction.user)
        await interaction.followup.send(embed=embeds[0], view=view)


async def setup(bot):
    await bot.add_cog(Suggestion(bot))