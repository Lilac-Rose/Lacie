import discord
from discord.ext import commands
from datetime import datetime, timedelta, timezone
from utils.logger import get_logger

logger = get_logger(__name__)

# Role whose assignment triggers the bot-trap check
ROLE_ID_TO_BAN = 1439354601672282335
# Channel for logging trap-role events
LOG_CHANNEL_ID = 1440055015711703242
# Fallback channel to ping the user if DMs are disabled
FALLBACK_CHANNEL_ID = 876772600704020533
# Members newer than this threshold are assumed to be bots and auto-banned
NEW_MEMBER_THRESHOLD_DAYS = 1


class AutoBanOnRole(commands.Cog):
    """Cog that automatically bans or warns users who receive the bot-trap role.

    When the trap role is assigned, the response depends on how long the
    member has been in the server:

    - New members (< 1 day): assumed to be bots — banned immediately with a
      7-day message purge and logged to LOG_CHANNEL_ID.
    - Established members (>= 1 day): the role is removed and they are warned
      via DM (or fallback channel ping if DMs are disabled).
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Watch for the trap role being added and take the appropriate action."""
        # Role was just added
        before_roles = set(before.roles)
        after_roles = set(after.roles)
        added_roles = after_roles - before_roles

        trap_role = None
        for role in added_roles:
            if role.id == ROLE_ID_TO_BAN:
                trap_role = role
                break

        if trap_role is None:
            return

        guild = after.guild

        # Check how long they've been in the server
        joined_at = after.joined_at or datetime.now(timezone.utc)
        server_join_age = datetime.now(timezone.utc) - joined_at
        is_new_member = server_join_age < timedelta(days=NEW_MEMBER_THRESHOLD_DAYS)

        if is_new_member:
            try:
                await guild.ban(
                    after,
                    reason="Bot automatically banned due to receiving bot trap role",
                    delete_message_days=7
                )
            except Exception as e:
                logger.error(f"Failed to auto-ban bot trap user {after.id}: {e}", exc_info=True)
                return

            channel = guild.get_channel(LOG_CHANNEL_ID)
            if channel is not None and isinstance(channel, discord.abc.Messageable):
                embed = discord.Embed(
                    title="🚫 Bot Detected & Auto-Banned",
                    description=(
                        f"**User:** {after.mention} `{after.id}`\n"
                        f"**Action:** Automatically banned\n"
                        f"**Reason:** Received bot-trap role (server member for: {server_join_age.days} days)"
                    ),
                    color=discord.Color.red()
                )
                embed.set_thumbnail(url=after.display_avatar.url)
                await channel.send(embed=embed)
        else:
            # Established member — warn and remove the trap role instead of banning
            warning_message = (
                f"**WARNING!** You were given a role that is designed to auto-ban bots. "
                f"Since you're an established member, the role has been removed instead. "
                f"Please be more careful next time."
            )

            dm_sent = False
            try:
                await after.send(warning_message)
                dm_sent = True
            except (discord.Forbidden, discord.HTTPException) as e:
                pass

            await after.remove_roles(trap_role, reason="Auto removed trap role from established member")

            if not dm_sent:
                # Fall back to pinging them in a public channel if DMs are closed
                fallback_channel = guild.get_channel(FALLBACK_CHANNEL_ID)
                if fallback_channel is not None and isinstance(fallback_channel, discord.abc.Messageable):
                    await fallback_channel.send(f"{after.mention}\n{warning_message}")

            log_channel = guild.get_channel(LOG_CHANNEL_ID)
            if log_channel is not None and isinstance(log_channel, discord.abc.Messageable):
                embed = discord.Embed(
                    title="⚠️ Trap Role Given to Existing User",
                    description=(
                        f"**User:** {after.mention} `{after.id}`\n"
                        f"**Action:** Role removed, user warned\n"
                        f"**DM Sent:** {'Yes' if dm_sent else 'No (pinged in channel)'}\n"
                        f"**Server Member For:** {server_join_age.days} days"
                    ),
                    color=discord.Color.orange()
                )
                embed.set_thumbnail(url=after.display_avatar.url)
                await log_channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("AutoBanOnRole cog loaded and ready!")


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoBanOnRole(bot))
