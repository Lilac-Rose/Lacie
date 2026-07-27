import io
import discord
from datetime import datetime, timezone, timedelta
from discord.ext import commands
from discord.ui import View, Button
from .loader import ModerationBase


class CleanBanCommand(ModerationBase):
    """Cog providing the !cleanban prefix command."""

    @commands.command(name="cleanban")
    @ModerationBase.is_senior_admin()
    async def cleanban(
        self,
        ctx,
        user: discord.User | discord.Member | str,
        days: int = 1,
        *,
        reason: str | None = None
    ):
        """Ban a user and delete their recent messages.

        Before banning, this command iterates all text channels and collects
        the user's messages from the past `days` days for the audit log.
        Discord then purges those messages via the delete_message_days parameter.

        Parameters
        ----------
        user:
            The user to ban (mention, ID, or User/Member object).
        days:
            Number of days of message history to delete (1–7, default 1).
        reason:
            Optional reason for the ban.
        """
        # Discord's ban API only supports 1–7 days of message deletion
        if days < 1 or days > 7:
            await ctx.send("Days must be between 1 and 7.")
            return

        # Resolve a raw ID string or mention into a User object
        if isinstance(user, str):
            user_id = user.strip("<@!>")
            try:
                user = await self.bot.fetch_user(int(user_id))
            except Exception:
                await ctx.send("Could not find that user. Please provide a valid mention or ID.")
                return

        view = View(timeout=30)
        confirmed = {"value": False}

        async def yes_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("You can't confirm this action.", ephemeral=True)
                return
            confirmed["value"] = True
            await interaction.response.edit_message(content="✅ Confirmed.", view=None)
            view.stop()

        async def no_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("You can't cancel this action.", ephemeral=True)
                return
            confirmed["value"] = False
            await interaction.response.edit_message(content="❌ Cancelled.", view=None)
            view.stop()

        yes_button = Button(label="Yes", style=discord.ButtonStyle.green)
        no_button = Button(label="No", style=discord.ButtonStyle.red)
        yes_button.callback = yes_callback
        no_button.callback = no_callback
        view.add_item(yes_button)
        view.add_item(no_button)

        user_ref = user.mention if hasattr(user, "mention") else str(user)
        await ctx.send(
            f"Are you sure you want to cleanban {user_ref}?\n"
            f"**This will delete their messages from the past {days} day(s) and ban them.**\n"
            f"Reason: {reason or 'No reason provided'}",
            view=view
        )

        await view.wait()
        if not confirmed["value"]:
            return

        if not ctx.guild:
            return

        # Collect the user's messages BEFORE banning so they can be preserved in the audit log
        collect_status = await ctx.send("📋 Collecting message history for audit log before banning...")
        deleted_messages = []
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
        for channel in ctx.guild.text_channels:
            if not channel.permissions_for(ctx.guild.me).read_message_history:
                continue
            try:
                async for msg in channel.history(limit=None, after=cutoff_dt, oldest_first=True):
                    if msg.author.id == user.id:
                        deleted_messages.append({
                            "channel": channel.name,
                            "channel_id": channel.id,
                            "message_id": msg.id,
                            "timestamp": msg.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                            "content": msg.content or "",
                            "attachments": [a.url for a in msg.attachments],
                        })
            except (discord.Forbidden, discord.HTTPException):
                pass

        try:
            await collect_status.delete()
        except discord.HTTPException:
            pass

        # DM before banning so the message is delivered while the user is still in the server
        try:
            await user.send(
                f"You have been **banned** from **{ctx.guild.name}**.\n"
                f"Messages from the past {days} day(s) have been deleted.\n"
                f"Reason: {reason or 'No reason provided'}"
            )
        except Exception:
            await ctx.send("Could not DM the user.")

        try:
            await ctx.guild.ban(
                discord.Object(id=user.id),
                reason=reason,
                delete_message_days=days
            )
            await ctx.send(
                f"{user_ref} has been banned.\n"
                f"Messages from the past {days} day(s) have been deleted."
                + (f" ({len(deleted_messages)} message(s) logged)" if deleted_messages else "")
            )
        except Exception as e:
            await ctx.send(f"Failed to ban user: `{e}`")
            return

        await self.log_infraction(ctx.guild.id, user.id, ctx.author.id, "cleanban", reason)

        logger = self.bot.get_cog("Logger")
        if logger:
            await logger.log_moderation_action(ctx.guild.id, "cleanban", user, ctx.author, reason)
            await logger.log_ban_messages(ctx.guild.id, user, deleted_messages, days)


async def setup(bot: commands.Bot):
    await bot.add_cog(CleanBanCommand(bot))
