import discord
from discord.ext import commands


class Welcome(commands.Cog):
    """Cog that sends a welcome DM and channel message when a new member completes onboarding.

    Two triggers fire _send_welcome: receiving their first real role (excluding
    @everyone) or the Discord pending/membership-screening flag clearing. A
    deduplication set ensures the welcome fires at most once per member per
    bot session, even if both triggers fire for the same join.

    Members holding the bot-trap role are silently skipped so bots never receive
    a welcome before being auto-banned.
    """

    def __init__(self, bot):
        self.bot = bot
        # In-memory dedup set — reset on restart, which is fine for a per-session guard
        self._welcomed: set[int] = set()

    async def _send_welcome(self, member):
        """Send the welcome DM and channel message for a newly onboarded member.

        Skips silently if the member has already been welcomed this session or
        holds the bot-trap role. Falls back to a channel ping if the DM fails.
        """
        if member.id in self._welcomed:
            return
        self._welcomed.add(member.id)

        bot_trap_role_id = 1439354601672282335
        if any(role.id == bot_trap_role_id for role in member.roles):
            return

        welcome_channel = self.bot.get_channel(876772600704020533)

        dm_embed = discord.Embed(
            title="Welcome to the server!",
            description=(
                "Please read <#1241579091597987880> and <#1238234316396429312> if you haven't already. "
                "Apart from that, any Paper Lily related discussion should go into the dedicated channel for it - "
                "and make sure to claim the spoiler chat role if that's what you want to talk about.\n\n"
                "Don't hesitate to ask the mods any questions using <@575252669443211264>, "
                "and we hope you enjoy your stay!"
            ),
            color=discord.Color.blurple()
        )
        dm_embed.set_footer(text=f"Joined {member.guild.name}")
        dm_embed.timestamp = discord.utils.utcnow()

        try:
            await member.send(embed=dm_embed)
            dm_success = True
        except discord.Forbidden:
            dm_success = False
        except discord.HTTPException:
            dm_success = False

        if welcome_channel and isinstance(welcome_channel, discord.abc.Messageable):
            if dm_success:
                await welcome_channel.send(f"Welcome {member.mention} to the server!")
            else:
                await welcome_channel.send(f"Welcome {member.mention} to the server! I couldn't DM you the welcome message, so <@692683410132566016> will do that")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Fire the welcome on first real role assignment or onboarding completion."""
        # Trigger 1: member receives their first real role (onboarding assigned a role)
        before_roles = [r for r in before.roles if r.name != "@everyone"]
        after_roles = [r for r in after.roles if r.name != "@everyone"]
        first_role = len(before_roles) == 0 and len(after_roles) > 0

        # Trigger 2: pending flag clears (onboarding complete, even if no role was assigned)
        completed_pending = before.pending and not after.pending

        if first_role or completed_pending:
            await self._send_welcome(after)


async def setup(bot):
    await bot.add_cog(Welcome(bot))
