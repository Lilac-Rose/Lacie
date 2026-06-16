import discord
from discord.ext import commands


class GoodBotListener(commands.Cog):
    """Responds to 'good bot' mentions with a blush emote."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Reply with a blush emote when someone mentions the bot and says 'good bot'."""
        if message.author.bot:
            return

        if self.bot.user and self.bot.user.mentioned_in(message) and "good bot" in message.content.lower():
            await message.reply("<:CatgirlLacieBlush:1283389963018440754>")


async def setup(bot: commands.Bot):
    await bot.add_cog(GoodBotListener(bot))
