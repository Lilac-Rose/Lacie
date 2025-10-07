import discord
from discord.ext import commands
from moderation.loader import ModerationBase, ADMIN_ROLE_ID
import asyncio

SALT_EMOJI_ID = 1074583707459010560

class SaltCommand(ModerationBase):
    def __init__(self, bot):
        self.bot = bot
        # Stores user IDs to salt: {guild_id: {user_id: reason}}
        self.salt_targets = {}

    @commands.command(name="salt")
    async def salt(self, ctx, member: discord.Member, *, reason: str = None):
        """React with salt emoji to the user's next message"""
        # Check if the author is a mod/admin
        if not any(role.id == ADMIN_ROLE_ID for role in ctx.author.roles):
            await ctx.send("You have no power here.")
            return

        guild_targets = self.salt_targets.setdefault(ctx.guild.id, {})

        if member.id in guild_targets:
            await ctx.send(f"{member.mention} is already marked to be salted on their next message.")
            return

        guild_targets[member.id] = reason
        await ctx.send(f"{member.mention} got salt thrown at them" + (f" for: {reason}" if reason else ""))

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
            guild_targets.pop(message.author.id)

async def setup(bot: commands.Bot):
    await bot.add_cog(SaltCommand(bot))
