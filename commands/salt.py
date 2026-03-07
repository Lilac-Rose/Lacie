import discord
from discord.ext import commands
from moderation.loader import ModerationBase
import asyncio
import random

SALT_EMOJI_ID = 1074583707459010560

class SaltCommand(ModerationBase):
    def __init__(self, bot):
        self.bot = bot
        # tracks who's queued to be salted: {guild_id: {user_id: reason}}
        # only persists in memory, resets on restart which is fine
        self.salt_targets = {}

    @commands.command(name="salt")
    @ModerationBase.is_admin()
    async def salt(self, ctx, member: discord.Member, *, reason: str = None):
        """React with salt emoji to the user's next message"""

        # easter egg — 1% chance of denying the command if used on this specific user
        if member.id == 252130669919076352:
            chance = random.randrange(1,101)
            if chance == 1:
                await ctx.send("https://tenor.com/view/you-didnt-say-the-magic-word-ah-ah-nope-wagging-finger-gif-17646607")
                return

        if member.id == ctx.author.id:
            await ctx.send("You cant salt yourself")
            return

        # setdefault so we don't have to check if the guild key exists
        guild_targets = self.salt_targets.setdefault(ctx.guild.id, {})

        if member.id in guild_targets:
            await ctx.send(f"{member.mention} is already marked to be salted on their next message.")
            return

        guild_targets[member.id] = reason
        await ctx.send(f"{member.mention} got salt thrown at them" + (f" for: {reason}" if reason else "."))

    @commands.Cog.listener()
    async def on_message(self, message):
        # ignore bots (except our own bot id — that one should still be saltable)
        if message.author.bot and message.author.id != 1409637508689563689 or not message.guild:
            return

        guild_targets = self.salt_targets.get(message.guild.id, {})
        if message.author.id in guild_targets:
            emoji = self.bot.get_emoji(SALT_EMOJI_ID)
            if emoji:
                try:
                    await message.add_reaction(emoji)
                except discord.HTTPException:
                    pass
            # remove them after reacting — one salt per queue
            guild_targets.pop(message.author.id)

async def setup(bot: commands.Bot):
    await bot.add_cog(SaltCommand(bot))
