import discord
from discord.ext import commands
from moderation.loader import ModerationBase
import asyncio

# Custom emoji ID you provided
SALT_EMOJI_ID = 1074583707459010560

class SaltCommand(ModerationBase):
    def __init__(self, bot):
        self.bot = bot
        # Stores user IDs to salt: {guild_id: {user_id: reason}}
        self.salt_targets = {}

    @commands.command(name="salt")
    @ModerationBase.is_admin()
    async def salt(self, ctx, member: discord.Member, *, reason: str = None):
        """React with salt emoji to the user's next message"""
        guild_targets = self.salt_targets.setdefault(ctx.guild.id, {})

        if member.id in guild_targets:
            await ctx.send(f"{member.mention} is already marked to be salted on their next message.")
            return

        guild_targets[member.id] = reason
        await ctx.send(f"{member.mention} got salt thrown at them for: {reason or 'no reason provided'}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        guild_targets = self.salt_targets.get(message.guild.id, {})
        if message.author.id in guild_targets:
            emoji = self.bot.get_emoji(SALT_EMOJI_ID)
            if emoji:
                try:
                    await message.add_reaction(emoji)
                except discord.HTTPException:
                    pass
            # Optionally you could DM the user or log the reason somewhere
            # Remove the user from the salt list after reacting
            guild_targets.pop(message.author.id)

async def setup(bot: commands.Bot):
    await bot.add_cog(SaltCommand(bot))
