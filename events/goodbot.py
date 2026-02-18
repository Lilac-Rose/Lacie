import discord
from discord.ext import commands

class GoodBotListener(commands.Cog):
    """Responds to 'good bot' mentions."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bot's own messages
        if message.author.bot:
            return

        # Check if bot is mentioned and message contains "good bot" (case insensitive)
        if self.bot.user.mentioned_in(message) and "good bot" in message.content.lower():
            await message.reply("<:CatgirlLacieBlush:1283389963018440754>")

async def setup(bot: commands.Bot):
    await bot.add_cog(GoodBotListener(bot))