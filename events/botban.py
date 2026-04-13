import discord
from discord.ext import commands
from datetime import datetime, timedelta, timezone
from utils.logger import get_logger

logger = get_logger(__name__)

ROLE_ID_TO_BAN = 1439354601672282335
LOG_CHANNEL_ID = 1440055015711703242
FALLBACK_CHANNEL_ID = 876772600704020533
NEW_MEMBER_THRESHOLD_DAYS = 1

class AutoBanOnRole(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
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