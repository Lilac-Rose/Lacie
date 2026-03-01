import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
from datetime import datetime
from embed.embed_color import get_embed_color
from pathlib import Path
from typing import Optional
import traceback
from utils.logger import get_logger

logger = get_logger(__name__)

ADMIN_ID = 252130669919076352
ADMIN_CHANNEL_ID = 1470441786810826884
BOT_DEV_ROLE_ID = 1470439484549234866


class DenyModal(discord.ui.Modal, title="Reason for denying suggestion"):
    reason = discord.ui.TextInput(label="Reason (optional)", style=discord.TextStyle.long, required=False, max_length=2000)

    def __init__(self, suggestion_id: int, user_id: int, suggestion_text: str, channel_id: int, admin_message_id: Optional[int], bot: commands.Bot, original_embed: discord.Embed):
        super().__init__()
        self.suggestion_id = suggestion_id
        self.user_id = user_id
        self.suggestion_text = suggestion_text
        self.channel_id = channel_id
        self.admin_message_id = admin_message_id
        self.bot = bot
        self.original_embed = original_embed

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)

            reason_text = self.reason.value or None

            db_path = Path(__file__).parent.parent / "data" / "suggestions.db"
            async with aiosqlite.connect(db_path) as db:
                await db.execute("UPDATE suggestions SET status = ?, reason = ? WHERE id = ?", ("Denied", reason_text, self.suggestion_id))
                await db.commit()

            await interaction.followup.send(f"❌ Suggestion #{self.suggestion_id} denied.", ephemeral=True)

            if self.admin_message_id:
                try:
                    admin_channel = self.bot.get_channel(ADMIN_CHANNEL_ID)
                    if admin_channel:
                        orig_msg = await admin_channel.fetch_message(self.admin_message_id)

                        updated_embed = self.original_embed.copy()
                        updated_embed.color = discord.Color.red()
                        updated_embed.title = f"❌ Denied Suggestion (ID: {self.suggestion_id})"

                        updated_embed.set_field_at(0, name="Suggested by", value=updated_embed.fields[0].value, inline=True)
                        updated_embed.set_field_at(1, name="Channel", value=updated_embed.fields[1].value, inline=True)
                        updated_embed.add_field(name="Status", value="Denied", inline=False)
                        updated_embed.add_field(name="Denied by", value=f"{interaction.user.mention}", inline=True)
                        updated_embed.add_field(name="Denied at", value=f"<t:{int(datetime.utcnow().timestamp())}:F>", inline=True)

                        if reason_text:
                            updated_embed.add_field(name="Reason", value=reason_text, inline=False)

                        disabled_view = SuggestionButtons(
                            self.bot,
                            suggestion_id=self.suggestion_id,
                            user_id=self.user_id,
                            suggestion_text=self.suggestion_text,
                            channel_id=self.channel_id,
                            admin_message_id=self.admin_message_id,
                            disabled=True
                        )
                        await orig_msg.edit(embed=updated_embed, view=disabled_view)
                except Exception as e:
                    logger.error(f"Failed to edit admin message: {e}")

            try:
                user = await self.bot.fetch_user(self.user_id)
                dm_note = f"❌ Your suggestion (ID: {self.suggestion_id}) — `{self.suggestion_text}` has been **denied**."
                if reason_text:
                    dm_note += f"\n**Reason:** {reason_text}"
                await user.send(dm_note)
            except Exception as e:
                logger.error(f"Failed to DM user: {e}")

            channel = self.bot.get_channel(self.channel_id)
            if channel:
                try:
                    msg = f"❌ Suggestion **#{self.suggestion_id}** (`{self.suggestion_text}`) has been **denied**."
                    if reason_text:
                        msg += f"\n**Reason:** {reason_text}"
                    await channel.send(msg)
                except Exception as e:
                    logger.error(f"Failed to send message in channel: {e}")

        except Exception as e:
            error_msg = f"❌ Error denying suggestion: {str(e)}\n```{traceback.format_exc()}```"
            logger.error(f"Error denying suggestion: {e}", exc_info=True)
            try:
                await interaction.followup.send(error_msg[:2000], ephemeral=True)
            except Exception:
                pass


class SuggestionButtons(discord.ui.View):
    def __init__(self, bot, suggestion_id=None, user_id=None, suggestion_text=None, channel_id=None, admin_message_id: Optional[int] = None, disabled: bool = False, show_complete: bool = False):
        super().__init__(timeout=None)
        self.bot = bot
        self.suggestion_id = suggestion_id
        self.user_id = user_id
        self.suggestion_text = suggestion_text
        self.channel_id = channel_id
        self.admin_message_id = admin_message_id

        approve_cid = f"suggest_approve_{suggestion_id}" if suggestion_id else "suggest_approve"
        deny_cid = f"suggest_deny_{suggestion_id}" if suggestion_id else "suggest_deny"
        complete_cid = f"suggest_complete_{suggestion_id}" if suggestion_id else "suggest_complete"

        if not show_complete:
            approve_btn = discord.ui.Button(label="Approve ✅", style=discord.ButtonStyle.success, custom_id=approve_cid, disabled=disabled)
            approve_btn.callback = self.approve
            self.add_item(approve_btn)

            deny_btn = discord.ui.Button(label="Deny ❌", style=discord.ButtonStyle.danger, custom_id=deny_cid, disabled=disabled)
            deny_btn.callback = self.deny
            self.add_item(deny_btn)
        else:
            complete_btn = discord.ui.Button(label="Mark Complete 🎉", style=discord.ButtonStyle.primary, custom_id=complete_cid, disabled=disabled)
            complete_btn.callback = self.complete
            self.add_item(complete_btn)

    async def approve(self, interaction: discord.Interaction):
        try:
            has_permission = (
                interaction.user.id == ADMIN_ID or
                any(role.id == BOT_DEV_ROLE_ID for role in interaction.user.roles)
            )

            if not has_permission:
                await interaction.response.send_message("You can't approve suggestions.", ephemeral=True)
                return

            if not self.suggestion_id:
                await interaction.response.send_message("⚠️ This button is no longer active.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)

            db_path = Path(__file__).parent.parent / "data" / "suggestions.db"
            async with aiosqlite.connect(db_path) as db:
                await db.execute("UPDATE suggestions SET status = ? WHERE id = ?", ("Approved", self.suggestion_id))
                await db.commit()

            await interaction.followup.send(f"✅ Suggestion #{self.suggestion_id} approved.", ephemeral=True)

            if self.admin_message_id:
                try:
                    admin_channel = self.bot.get_channel(ADMIN_CHANNEL_ID)
                    if admin_channel:
                        orig_msg = await admin_channel.fetch_message(self.admin_message_id)

                        updated_embed = orig_msg.embeds[0].copy()
                        updated_embed.color = discord.Color.green()
                        updated_embed.title = f"✅ Approved Suggestion (ID: {self.suggestion_id})"

                        updated_embed.add_field(name="Status", value="Approved", inline=False)
                        updated_embed.add_field(name="Approved by", value=f"{interaction.user.mention}", inline=True)
                        updated_embed.add_field(name="Approved at", value=f"<t:{int(datetime.utcnow().timestamp())}:F>", inline=True)

                        complete_view = SuggestionButtons(
                            self.bot,
                            suggestion_id=self.suggestion_id,
                            user_id=self.user_id,
                            suggestion_text=self.suggestion_text,
                            channel_id=self.channel_id,
                            admin_message_id=self.admin_message_id,
                            disabled=False,
                            show_complete=True
                        )
                        await orig_msg.edit(embed=updated_embed, view=complete_view)
                except Exception as e:
                    logger.error(f"Failed to edit admin message: {e}")

            try:
                user = await self.bot.fetch_user(self.user_id)
                await user.send(f"✅ Your suggestion (ID: {self.suggestion_id}) — `{self.suggestion_text}` has been **approved!**")
            except Exception as e:
                logger.error(f"Failed to DM user: {e}")

            channel = self.bot.get_channel(self.channel_id)
            if channel:
                try:
                    await channel.send(f"✅ Suggestion **#{self.suggestion_id}** (`{self.suggestion_text}`) has been **approved!**")
                except Exception as e:
                    logger.error(f"Failed to send message in channel: {e}")

        except Exception as e:
            error_msg = f"❌ Error approving suggestion: {str(e)}\n```{traceback.format_exc()}```"
            logger.error(f"Error approving suggestion: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(error_msg[:2000], ephemeral=True)
                else:
                    await interaction.followup.send(error_msg[:2000], ephemeral=True)
            except Exception:
                pass

    async def deny(self, interaction: discord.Interaction):
        try:
            has_permission = (
                interaction.user.id == ADMIN_ID or
                any(role.id == BOT_DEV_ROLE_ID for role in interaction.user.roles)
            )

            if not has_permission:
                await interaction.response.send_message("You can't deny suggestions.", ephemeral=True)
                return

            if not self.suggestion_id:
                await interaction.response.send_message("⚠️ This button is no longer active.", ephemeral=True)
                return

            admin_channel = self.bot.get_channel(ADMIN_CHANNEL_ID)
            if admin_channel and self.admin_message_id:
                try:
                    orig_msg = await admin_channel.fetch_message(self.admin_message_id)
                    original_embed = orig_msg.embeds[0] if orig_msg.embeds else None
                except Exception:
                    original_embed = None
            else:
                original_embed = None

            modal = DenyModal(
                suggestion_id=self.suggestion_id,
                user_id=self.user_id,
                suggestion_text=self.suggestion_text,
                channel_id=self.channel_id,
                admin_message_id=self.admin_message_id,
                bot=self.bot,
                original_embed=original_embed
            )
            await interaction.response.send_modal(modal)
        except Exception as e:
            error_msg = f"❌ Error opening deny modal: {str(e)}\n```{traceback.format_exc()}```"
            logger.error(f"Error opening deny modal: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(error_msg[:2000], ephemeral=True)
                else:
                    await interaction.followup.send(error_msg[:2000], ephemeral=True)
            except Exception:
                pass

    async def complete(self, interaction: discord.Interaction):
        try:
            has_permission = (
                interaction.user.id == ADMIN_ID or
                any(role.id == BOT_DEV_ROLE_ID for role in interaction.user.roles)
            )

            if not has_permission:
                await interaction.response.send_message("You can't mark suggestions as complete.", ephemeral=True)
                return

            if not self.suggestion_id:
                await interaction.response.send_message("⚠️ This button is no longer active.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)

            db_path = Path(__file__).parent.parent / "data" / "suggestions.db"
            async with aiosqlite.connect(db_path) as db:
                async with db.execute("SELECT status FROM suggestions WHERE id = ?", (self.suggestion_id,)) as cursor:
                    row = await cursor.fetchone()
                    if not row or row[0] != "Approved":
                        await interaction.followup.send("⚠️ This suggestion must be approved before marking as complete.", ephemeral=True)
                        return

                await db.execute("UPDATE suggestions SET status = ? WHERE id = ?", ("Completed", self.suggestion_id))
                await db.commit()

            await interaction.followup.send(f"🎉 Suggestion #{self.suggestion_id} marked as completed!", ephemeral=True)

            if self.admin_message_id:
                try:
                    admin_channel = self.bot.get_channel(ADMIN_CHANNEL_ID)
                    if admin_channel:
                        orig_msg = await admin_channel.fetch_message(self.admin_message_id)

                        updated_embed = orig_msg.embeds[0].copy()
                        updated_embed.color = discord.Color.blue()
                        updated_embed.title = f"🎉 Completed Suggestion (ID: {self.suggestion_id})"

                        for i, field in enumerate(updated_embed.fields):
                            if field.name == "Status":
                                updated_embed.set_field_at(i, name="Status", value="Completed", inline=field.inline)
                                break

                        updated_embed.add_field(name="Completed by", value=f"{interaction.user.mention}", inline=True)
                        updated_embed.add_field(name="Completed at", value=f"<t:{int(datetime.utcnow().timestamp())}:F>", inline=True)

                        disabled_view = SuggestionButtons(
                            self.bot,
                            suggestion_id=self.suggestion_id,
                            user_id=self.user_id,
                            suggestion_text=self.suggestion_text,
                            channel_id=self.channel_id,
                            admin_message_id=self.admin_message_id,
                            disabled=True,
                            show_complete=True
                        )
                        await orig_msg.edit(embed=updated_embed, view=disabled_view)
                except Exception as e:
                    logger.error(f"Failed to edit admin message: {e}")

            try:
                user = await self.bot.fetch_user(self.user_id)
                await user.send(f"🎉 Your suggestion (ID: {self.suggestion_id}) — `{self.suggestion_text}` has been **implemented!**")
            except Exception as e:
                logger.error(f"Failed to DM user: {e}")

            channel = self.bot.get_channel(self.channel_id)
            if channel:
                try:
                    await channel.send(f"🎉 Suggestion **#{self.suggestion_id}** (`{self.suggestion_text}`) has been marked as **completed!**")
                except Exception as e:
                    logger.error(f"Failed to send message in channel: {e}")

        except Exception as e:
            error_msg = f"❌ Error completing suggestion: {str(e)}\n```{traceback.format_exc()}```"
            logger.error(f"Error completing suggestion: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(error_msg[:2000], ephemeral=True)
                else:
                    await interaction.followup.send(error_msg[:2000], ephemeral=True)
            except Exception:
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

    def __init__(self, bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "data" / "suggestions.db"
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

        async with self.db.execute("SELECT id, user_id, suggestion, channel_id, admin_message_id, status FROM suggestions WHERE status IN (?, ?)", ("Pending", "Approved")) as cursor:
            rows = await cursor.fetchall()

        for sid, uid, suggestion_text, channel_id, admin_msg_id, status in rows:
            if admin_msg_id:
                view = SuggestionButtons(
                    self.bot,
                    suggestion_id=sid,
                    user_id=uid,
                    suggestion_text=suggestion_text,
                    channel_id=channel_id,
                    admin_message_id=admin_msg_id,
                    show_complete=(status == "Approved")
                )
                self.bot.add_view(view, message_id=admin_msg_id)
                logger.info(f"Re-registered view for suggestion #{sid} (message {admin_msg_id}, status: {status})")

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
                        color=get_embed_color(interaction.user.id),
                        timestamp=datetime.utcnow()
                    )
                    embed.add_field(name="Suggested by", value=f"{interaction.user} ({interaction.user.id})")
                    embed.add_field(name="Channel", value=f"<#{interaction.channel_id}>")

                    view = SuggestionButtons(self.bot, suggestion_id, interaction.user.id, idea, interaction.channel_id)
                    sent = await admin_channel.send(embed=embed, view=view)

                    await self.db.execute("UPDATE suggestions SET admin_message_id = ? WHERE id = ?", (sent.id, suggestion_id))
                    await self.db.commit()

                    persistent_view = SuggestionButtons(
                        self.bot,
                        suggestion_id,
                        interaction.user.id,
                        idea,
                        interaction.channel_id,
                        admin_message_id=sent.id
                    )
                    self.bot.add_view(persistent_view, message_id=sent.id)
                    logger.info(f"Registered persistent view for suggestion #{suggestion_id} (message {sent.id})")

            except Exception as e:
                logger.error(f"Failed to send message to admin channel: {e}", exc_info=True)

        except Exception as e:
            error_msg = f"❌ An error occurred: {str(e)}\n```{traceback.format_exc()}```"
            logger.error(f"Error in suggest command: {e}", exc_info=True)
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
            except Exception:
                embed.add_field(name="Suggested by", value=f"<@{user_id}>", inline=True)

            embed.add_field(name="Status", value=status, inline=True)
            embed.add_field(name="Channel", value=f"<#{channel_id}>", inline=True)

            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            error_msg = f"❌ An error occurred: {str(e)}\n```{traceback.format_exc()}```"
            logger.error(f"Error in viewsuggestion command: {e}", exc_info=True)
            await interaction.followup.send(error_msg[:2000])

    @app_commands.command(name="complete", description="Mark an approved suggestion as completed (Admin only)")
    async def completesuggestion(self, interaction: discord.Interaction, suggestion_id: int):
        await interaction.response.defer(ephemeral=False)

        try:
            has_permission = (
                interaction.user.id == ADMIN_ID or
                any(role.id == BOT_DEV_ROLE_ID for role in interaction.user.roles)
            )

            if not has_permission:
                await interaction.followup.send("You don't have permission to do that.")
                return

            async with self.db.execute("SELECT user_id, suggestion, status, channel_id, admin_message_id FROM suggestions WHERE id = ?", (suggestion_id,)) as cursor:
                row = await cursor.fetchone()

            if not row:
                await interaction.followup.send("❌ Suggestion not found.")
                return

            user_id, suggestion_text, status, channel_id, admin_message_id = row
            if status != "Approved":
                await interaction.followup.send("⚠️ This suggestion must be approved before marking as complete.")
                return

            await self.db.execute("UPDATE suggestions SET status = ? WHERE id = ?", ("Completed", suggestion_id))
            await self.db.commit()

            await interaction.followup.send(f"✅ Suggestion #{suggestion_id} marked as completed!")

            if admin_message_id:
                try:
                    admin_channel = self.bot.get_channel(ADMIN_CHANNEL_ID)
                    if admin_channel:
                        orig_msg = await admin_channel.fetch_message(admin_message_id)

                        updated_embed = orig_msg.embeds[0].copy()
                        updated_embed.color = discord.Color.blue()
                        updated_embed.title = f"🎉 Completed Suggestion (ID: {suggestion_id})"

                        for i, field in enumerate(updated_embed.fields):
                            if field.name == "Status":
                                updated_embed.set_field_at(i, name="Status", value="Completed", inline=field.inline)
                                break

                        updated_embed.add_field(name="Completed by", value=f"{interaction.user.mention}", inline=True)
                        updated_embed.add_field(name="Completed at", value=f"<t:{int(datetime.utcnow().timestamp())}:F>", inline=True)

                        disabled_view = SuggestionButtons(
                            self.bot,
                            suggestion_id=suggestion_id,
                            user_id=user_id,
                            suggestion_text=suggestion_text,
                            channel_id=channel_id,
                            admin_message_id=admin_message_id,
                            disabled=True,
                            show_complete=True
                        )
                        await orig_msg.edit(embed=updated_embed, view=disabled_view)
                except Exception as e:
                    logger.error(f"Failed to edit admin message: {e}")

            try:
                user = await self.bot.fetch_user(user_id)
                await user.send(f"🎉 Your suggestion (ID: {suggestion_id}) — `{suggestion_text}` has been **implemented!**")
            except Exception:
                pass

            channel = self.bot.get_channel(channel_id)
            if channel:
                await channel.send(f"🎉 Suggestion **#{suggestion_id}** (`{suggestion_text}`) has been marked as **completed!**")

        except Exception as e:
            error_msg = f"❌ An error occurred: {str(e)}\n```{traceback.format_exc()}```"
            logger.error(f"Error in completesuggestion command: {e}", exc_info=True)
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
            logger.error(f"Error in listsuggestions command: {e}", exc_info=True)
            await interaction.followup.send(error_msg[:2000])

    @app_commands.command(name="stats", description="View suggestion stats for yourself or another user")
    async def suggestionstats(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=False)

        try:
            target = member or interaction.user

            async with self.db.execute(
                "SELECT COUNT(*) FROM suggestions WHERE user_id = ?", (target.id,)
            ) as cursor:
                total = (await cursor.fetchone())[0]

            async with self.db.execute(
                "SELECT COUNT(*) FROM suggestions WHERE user_id = ? AND status IN (?, ?)",
                (target.id, "Approved", "Completed")
            ) as cursor:
                accepted = (await cursor.fetchone())[0]

            async with self.db.execute(
                "SELECT COUNT(*) FROM suggestions WHERE user_id = ? AND status = ?",
                (target.id, "Denied")
            ) as cursor:
                rejected = (await cursor.fetchone())[0]

            embed = discord.Embed(
                title=f"📊 Suggestion Stats — {target.display_name}",
                color=get_embed_color(target.id)
            )
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.add_field(name="Total Submitted", value=str(total), inline=True)
            embed.add_field(name="Accepted", value=str(accepted), inline=True)
            embed.add_field(name="Rejected", value=str(rejected), inline=True)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            error_msg = f"❌ An error occurred: {str(e)}\n```{traceback.format_exc()}```"
            logger.error(f"Error in suggestionstats command: {e}", exc_info=True)
            await interaction.followup.send(error_msg[:2000])

    @app_commands.command(name="todo", description="View your approved suggestions to-do list")
    async def todolist(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=False)

        try:
            has_permission = (
                interaction.user.id == ADMIN_ID or
                any(role.id == BOT_DEV_ROLE_ID for role in interaction.user.roles)
            )
            if not has_permission:
                await interaction.followup.send("This command is restricted to Lacie bot devs.", ephemeral=True)
                return

            target_user = member if member else interaction.user

            admin_channel = self.bot.get_channel(ADMIN_CHANNEL_ID)
            if not admin_channel:
                await interaction.followup.send("❌ Admin channel not found.")
                return

            async with self.db.execute(
                "SELECT id, user_id, suggestion, admin_message_id FROM suggestions WHERE status = ? ORDER BY id DESC",
                ("Approved",)
            ) as cursor:
                rows = await cursor.fetchall()

            if not rows:
                await interaction.followup.send(f"No approved suggestions found.")
                return

            user_approved = []
            for sid, uid, suggestion_text, admin_msg_id in rows:
                if admin_msg_id:
                    try:
                        msg = await admin_channel.fetch_message(admin_msg_id)
                        if msg.embeds:
                            embed = msg.embeds[0]
                            for field in embed.fields:
                                if field.name == "Approved by" and target_user.mention in field.value:
                                    user_approved.append((sid, uid, suggestion_text))
                                    break
                    except Exception as e:
                        logger.error(f"Failed to fetch message {admin_msg_id}: {e}")
                        continue

            if not user_approved:
                if member and member != interaction.user:
                    await interaction.followup.send(f"{target_user.mention} hasn't approved any suggestions yet.")
                else:
                    await interaction.followup.send("You haven't approved any suggestions yet.")
                return

            embeds = []
            per_page = 10
            for i in range(0, len(user_approved), per_page):
                embed = discord.Embed(
                    title=f"📝 {target_user.display_name}'s To-Do List (Page {i//per_page + 1})",
                    description=f"Approved suggestions waiting to be completed",
                    color=discord.Color.gold()
                )
                embed.set_thumbnail(url=target_user.display_avatar.url)

                for sid, uid, suggestion_text in user_approved[i:i+per_page]:
                    embed.add_field(
                        name=f"ID: {sid}",
                        value=f"**Suggested by:** <@{uid}>\n**Idea:** {suggestion_text[:150]}{'...' if len(suggestion_text) > 150 else ''}",
                        inline=False
                    )

                embed.set_footer(text=f"Total approved: {len(user_approved)}")
                embeds.append(embed)

            view = PaginationView(embeds, interaction.user)
            await interaction.followup.send(embed=embeds[0], view=view)

        except Exception as e:
            error_msg = f"❌ An error occurred: {str(e)}\n```{traceback.format_exc()}```"
            logger.error(f"Error in todolist command: {e}", exc_info=True)
            await interaction.followup.send(error_msg[:2000])


async def setup(bot):
    await bot.add_cog(Suggestion(bot))
