import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
from datetime import datetime
import os
from typing import Optional
import traceback

ADMIN_ID = 252130669919076352
ADMIN_CHANNEL_ID = 1470441786810826884


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
        try:
            # Defer the response immediately to prevent timeout
            await interaction.response.defer(ephemeral=False)
            
            reason_text = self.reason.value or None

            db_path = os.path.join(os.path.dirname(__file__), "suggestions.db")
            async with aiosqlite.connect(db_path) as db:
                await db.execute("UPDATE suggestions SET status = ?, reason = ? WHERE id = ?", ("Denied", reason_text, self.suggestion_id))
                await db.commit()

            # Use followup instead of response since we deferred
            await interaction.followup.send(f"❌ Suggestion #{self.suggestion_id} denied.", ephemeral=False)

            # Disable buttons on the admin message
            if self.admin_message_id:
                try:
                    admin_channel = self.bot.get_channel(ADMIN_CHANNEL_ID)
                    if admin_channel:
                        orig_msg = await admin_channel.fetch_message(self.admin_message_id)
                        disabled_view = SuggestionButtons(
                            self.bot, 
                            suggestion_id=self.suggestion_id, 
                            user_id=self.user_id, 
                            suggestion_text=self.suggestion_text, 
                            channel_id=self.channel_id, 
                            admin_message_id=self.admin_message_id, 
                            disabled=True
                        )
                        await orig_msg.edit(view=disabled_view)
                except Exception as e:
                    print(f"Failed to edit admin message: {e}")

            # Send DM to user
            try:
                user = await self.bot.fetch_user(self.user_id)
                dm_note = f"❌ Your suggestion (ID: {self.suggestion_id}) — `{self.suggestion_text}` has been **denied**."
                if reason_text:
                    dm_note += f"\n**Reason:** {reason_text}"
                await user.send(dm_note)
            except Exception as e:
                print(f"Failed to DM user: {e}")

            # Send message in original channel
            channel = self.bot.get_channel(self.channel_id)
            if channel:
                try:
                    msg = f"❌ Suggestion **#{self.suggestion_id}** (`{self.suggestion_text}`) has been **denied**."
                    if reason_text:
                        msg += f"\n**Reason:** {reason_text}"
                    await channel.send(msg)
                except Exception as e:
                    print(f"Failed to send message in channel: {e}")

        except Exception as e:
            error_msg = f"❌ Error denying suggestion: {str(e)}\n```{traceback.format_exc()}```"
            print(error_msg)
            try:
                await interaction.followup.send(error_msg[:2000], ephemeral=True)
            except:
                pass


class SuggestionButtons(discord.ui.View):
    def __init__(self, bot, suggestion_id=None, user_id=None, suggestion_text=None, channel_id=None, admin_message_id: Optional[int] = None, disabled: bool = False):
        super().__init__(timeout=None)
        self.bot = bot
        self.suggestion_id = suggestion_id
        self.user_id = user_id
        self.suggestion_text = suggestion_text
        self.channel_id = channel_id
        self.admin_message_id = admin_message_id

        approve_cid = f"suggest_approve_{suggestion_id}" if suggestion_id else "suggest_approve"
        deny_cid = f"suggest_deny_{suggestion_id}" if suggestion_id else "suggest_deny"

        approve_btn = discord.ui.Button(label="Approve ✅", style=discord.ButtonStyle.success, custom_id=approve_cid, disabled=disabled)
        approve_btn.callback = self.approve
        self.add_item(approve_btn)

        deny_btn = discord.ui.Button(label="Deny ❌", style=discord.ButtonStyle.danger, custom_id=deny_cid, disabled=disabled)
        deny_btn.callback = self.deny
        self.add_item(deny_btn)

    async def approve(self, interaction: discord.Interaction):
        try:
            if interaction.user.id != ADMIN_ID:
                await interaction.response.send_message("❌ You can't approve suggestions.", ephemeral=True)
                return

            if not self.suggestion_id:
                await interaction.response.send_message("⚠️ This button is no longer active.", ephemeral=True)
                return

            # Defer immediately to prevent timeout
            await interaction.response.defer(ephemeral=False)

            db_path = os.path.join(os.path.dirname(__file__), "suggestions.db")
            async with aiosqlite.connect(db_path) as db:
                await db.execute("UPDATE suggestions SET status = ? WHERE id = ?", ("Approved", self.suggestion_id))
                await db.commit()

            # Use followup since we deferred
            await interaction.followup.send(f"✅ Suggestion #{self.suggestion_id} approved.", ephemeral=False)

            # Disable buttons on the admin message
            if self.admin_message_id:
                try:
                    admin_channel = self.bot.get_channel(ADMIN_CHANNEL_ID)
                    if admin_channel:
                        orig_msg = await admin_channel.fetch_message(self.admin_message_id)
                        disabled_view = SuggestionButtons(
                            self.bot, 
                            suggestion_id=self.suggestion_id, 
                            user_id=self.user_id, 
                            suggestion_text=self.suggestion_text, 
                            channel_id=self.channel_id, 
                            admin_message_id=self.admin_message_id, 
                            disabled=True
                        )
                        await orig_msg.edit(view=disabled_view)
                except Exception as e:
                    print(f"Failed to edit admin message: {e}")

            # Send DM to user
            try:
                user = await self.bot.fetch_user(self.user_id)
                await user.send(f"✅ Your suggestion (ID: {self.suggestion_id}) — `{self.suggestion_text}` has been **approved!**")
            except Exception as e:
                print(f"Failed to DM user: {e}")

            # Send message in original channel
            channel = self.bot.get_channel(self.channel_id)
            if channel:
                try:
                    await channel.send(f"✅ Suggestion **#{self.suggestion_id}** (`{self.suggestion_text}`) has been **approved!**")
                except Exception as e:
                    print(f"Failed to send message in channel: {e}")

        except Exception as e:
            error_msg = f"❌ Error approving suggestion: {str(e)}\n```{traceback.format_exc()}```"
            print(error_msg)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(error_msg[:2000], ephemeral=True)
                else:
                    await interaction.followup.send(error_msg[:2000], ephemeral=True)
            except:
                pass

    async def deny(self, interaction: discord.Interaction):
        try:
            if interaction.user.id != ADMIN_ID:
                await interaction.response.send_message("❌ You can't deny suggestions.", ephemeral=True)
                return

            if not self.suggestion_id:
                await interaction.response.send_message("⚠️ This button is no longer active.", ephemeral=True)
                return

            modal = DenyModal(
                suggestion_id=self.suggestion_id, 
                user_id=self.user_id, 
                suggestion_text=self.suggestion_text, 
                channel_id=self.channel_id, 
                admin_message_id=self.admin_message_id, 
                bot=self.bot
            )
            await interaction.response.send_modal(modal)
        except Exception as e:
            error_msg = f"❌ Error opening deny modal: {str(e)}\n```{traceback.format_exc()}```"
            print(error_msg)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(error_msg[:2000], ephemeral=True)
                else:
                    await interaction.followup.send(error_msg[:2000], ephemeral=True)
            except:
                pass


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


class Suggestion(commands.GroupCog, name="suggest"):
    """Suggestion commands"""

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
            if admin_msg_id:  # Only register if we have a message ID
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

    @app_commands.command(name="submit", description="Submit a suggestion")
    async def suggest(self, interaction: discord.Interaction, idea: str):
        await interaction.response.defer(ephemeral=False)

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
                admin_channel = self.bot.get_channel(ADMIN_CHANNEL_ID)
                if admin_channel:
                    embed = discord.Embed(
                        title=f"New Suggestion (ID: {suggestion_id})",
                        description=idea,
                        color=discord.Color.blurple(),
                        timestamp=datetime.utcnow()
                    )
                    embed.add_field(name="Suggested by", value=f"{interaction.user} ({interaction.user.id})")
                    embed.add_field(name="Channel", value=f"<#{interaction.channel_id}>")

                    view = SuggestionButtons(self.bot, suggestion_id, interaction.user.id, idea, interaction.channel_id)
                    sent = await admin_channel.send(embed=embed, view=view)

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
                print(f"Failed to send message to admin channel: {e}")
                traceback.print_exc()

        except Exception as e:
            error_msg = f"❌ An error occurred: {str(e)}\n```{traceback.format_exc()}```"
            print(error_msg)
            await interaction.followup.send(error_msg[:2000])

    @app_commands.command(name="view", description="View full details of a suggestion")
    async def viewsuggestion(self, interaction: discord.Interaction, suggestion_id: int):
        await interaction.response.defer(ephemeral=False)

        try:
            async with self.db.execute("SELECT user_id, suggestion, status, channel_id, reason FROM suggestions WHERE id = ?", (suggestion_id,)) as cursor:
                row = await cursor.fetchone()

            if not row:
                await interaction.followup.send("❌ Suggestion not found.")
                return

            user_id, suggestion_text, status, channel_id, reason = row

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

        except Exception as e:
            error_msg = f"❌ An error occurred: {str(e)}\n```{traceback.format_exc()}```"
            print(error_msg)
            await interaction.followup.send(error_msg[:2000])

    @app_commands.command(name="complete", description="Mark an approved suggestion as completed (Admin only)")
    async def completesuggestion(self, interaction: discord.Interaction, suggestion_id: int):
        await interaction.response.defer(ephemeral=False)

        try:
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

        except Exception as e:
            error_msg = f"❌ An error occurred: {str(e)}\n```{traceback.format_exc()}```"
            print(error_msg)
            await interaction.followup.send(error_msg[:2000])

    @app_commands.command(name="list", description="List suggestions with optional status filter")
    @app_commands.choices(status=[
        app_commands.Choice(name="All", value="All"),
        app_commands.Choice(name="Pending", value="Pending"),
        app_commands.Choice(name="Approved", value="Approved"),
        app_commands.Choice(name="Denied", value="Denied"),
        app_commands.Choice(name="Completed", value="Completed")
    ])
    async def listsuggestions(self, interaction: discord.Interaction, status: app_commands.Choice[str] = None):
        await interaction.response.defer(ephemeral=False)

        try:
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

        except Exception as e:
            error_msg = f"❌ An error occurred: {str(e)}\n```{traceback.format_exc()}```"
            print(error_msg)
            await interaction.followup.send(error_msg[:2000])


async def setup(bot):
    await bot.add_cog(Suggestion(bot))