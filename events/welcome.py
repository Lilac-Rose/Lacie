import discord
from discord.ext import commands

class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    async def _send_welcome(self, member):
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

        if welcome_channel:
            if dm_success:
                await welcome_channel.send(f"Welcome {member.mention} to the server!")
            else:
                await welcome_channel.send(f"Welcome {member.mention} to the server! I couldn't DM you the welcome message, so <@692683410132566016> will do that")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        # If the server uses membership screening/onboarding, wait until they complete it
        if member.pending:
            return
        await self._send_welcome(member)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # Fires when a member completes onboarding (pending: True -> False)
        if before.pending and not after.pending:
            await self._send_welcome(after)

async def setup(bot):
    await bot.add_cog(Welcome(bot))