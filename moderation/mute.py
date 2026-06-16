import discord
from discord.ext import commands, tasks
from discord.ui import View, Button
import asyncio
import re
import sqlite3
from pathlib import Path
from datetime import timedelta, datetime
from .loader import ModerationBase
from utils.logger import get_logger

_logger = get_logger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "moderation.db"

# Role ID for the server's muted role
MUTE_ROLE_ID = 982702037517090836


class MuteCommand(ModerationBase):
    """Cog providing the !mute prefix command with automatic expiry.

    Mutes are tracked in a persistent `mutes` table so they survive bot
    restarts. A background task checks for expired mutes every minute.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.check_mutes.start()

    async def cog_unload(self):
        """Cancel the background task and close the DB when the cog unloads."""
        self.check_mutes.cancel()
        await super().cog_unload()

    @commands.command(name="mute")
    @ModerationBase.is_admin()
    async def mute(self, ctx, user: discord.Member, duration: str, *, reason: str | None = None):
        """Mute a member for a specified duration.

        Applies the mute role and schedules automatic removal. The mute is
        persisted to the database so the bot can restore it after a restart.

        Parameters
        ----------
        user:
            The server member to mute.
        duration:
            Duration string using suffix notation: w (weeks), d (days),
            h (hours), m (minutes). Example: 1w, 5d, 12h, 30m.
        reason:
            Optional reason for the mute.
        """
        match = re.match(r"(\d+)([wdhm])", duration.lower())
        if not match:
            await ctx.send("Invalid duration format. Use **1w**, **5d**, **12h**, **30m**, etc.")
            return

        value, unit = match.groups()
        value = int(value)
        if unit == "w":
            delta = timedelta(weeks=value)
        elif unit == "d":
            delta = timedelta(days=value)
        elif unit == "h":
            delta = timedelta(hours=value)
        elif unit == "m":
            delta = timedelta(minutes=value)

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

        await ctx.send(
            f"Are you sure you want to mute {user.mention} for **{duration}**? "
            f"Reason: {reason or 'No reason provided'}",
            view=view
        )
        await view.wait()
        if not confirmed["value"]:
            return

        if not ctx.guild:
            return

        mute_role = ctx.guild.get_role(MUTE_ROLE_ID)
        if not mute_role:
            await ctx.send("Mute role not found in server.")
            return

        await user.add_roles(mute_role, reason=reason)
        try:
            await user.send(
                f"You have been muted in **{ctx.guild.name}** for **{duration}**.\n"
                f"Reason: {reason or 'No reason provided'}"
            )
        except Exception:
            await ctx.send("Could not DM the user.")

        await self.log_infraction(ctx.guild.id, user.id, ctx.author.id, "mute", reason)
        await ctx.send(f"{user.mention} has been muted for **{duration}**.")

        # Persist the mute so it survives a restart
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS mutes (
            user_id INTEGER,
            guild_id INTEGER,
            channel_id INTEGER,
            unmute_time TEXT
        )
        """)
        unmute_time = (datetime.utcnow() + delta).isoformat()
        c.execute(
            "INSERT INTO mutes (user_id, guild_id, channel_id, unmute_time) VALUES (?, ?, ?, ?)",
            (user.id, ctx.guild.id, ctx.channel.id, unmute_time)
        )
        conn.commit()
        conn.close()

        logger = self.bot.get_cog("Logger")
        if logger:
            await logger.log_moderation_action(ctx.guild.id, "mute", user, ctx.author, reason, duration)

        # Schedule the automatic unmute as a fire-and-forget coroutine
        asyncio.create_task(self.schedule_unmute(user.id, ctx.guild.id, ctx.channel.id, delta.total_seconds()))

    async def schedule_unmute(self, user_id, guild_id, channel_id, delay):
        """Wait for the mute duration to expire, then remove the mute role.

        Also handles the case where the mute was manually removed before
        expiry — if the DB entry is already gone, this exits without action.
        """
        await asyncio.sleep(delay)

        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.execute("SELECT 1 FROM mutes WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
            if not c.fetchone():
                # Mute was manually removed before expiry
                return
            c.execute("DELETE FROM mutes WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
            conn.commit()
        finally:
            conn.close()

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        member = guild.get_member(user_id)
        if not member:
            return
        mute_role = guild.get_role(MUTE_ROLE_ID)
        if not mute_role:
            return

        try:
            await member.remove_roles(mute_role, reason="Mute duration expired")

            log_cog = self.bot.get_cog("Logger")
            if log_cog:
                await log_cog.log_moderation_action(
                    guild_id, "unmute", member, self.bot.user, "Mute duration expired"
                )
        except Exception as e:
            _logger.error(f"Failed to remove mute role from {user_id}: {e}", exc_info=True)

    @tasks.loop(minutes=1)
    async def check_mutes(self):
        """Background task: check for expired mutes every minute and remove them.

        This ensures mutes are cleaned up even if the bot was restarted and
        the scheduled_unmute task was never created for a given entry.
        """
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            now = datetime.utcnow().isoformat()
            c.execute(
                "SELECT user_id, guild_id, channel_id, unmute_time FROM mutes WHERE unmute_time <= ?",
                (now,)
            )
            expired = c.fetchall()
        finally:
            conn.close()

        for user_id, guild_id, channel_id, _ in expired:
            # Delay of 0 so they run immediately on the next event loop iteration
            asyncio.create_task(self.schedule_unmute(user_id, guild_id, channel_id, 0))


async def setup(bot: commands.Bot):
    await bot.add_cog(MuteCommand(bot))
