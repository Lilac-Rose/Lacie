"""import discord
from discord.ext import commands
from discord import app_commands
import random

class Magic8ball(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="magic8ball")
    async def magic8ball(self, interaction: discord.Interaction, question: str):

        responses = ["It is certain", "It is decidedly so", "Without a doubt", "Yes definitely", "You may rely on it", "As I see it, yes", "Most likely", "Outlook good", "Yes", "Signs point to yes", "Reply hazy, try again", "Ask again later", "Better not tell you now", "Cannot predict now", "Concentrate and ask again", "Don't count on it", "My reply is no", "My sources say no", "Outlook not so good", "Very doubtful"]

        response_index = random.randrange(0, len(responses))

        await interaction.response.send_message(f"🎱 Question: {question}\nAnswer: {responses[response_index]}")

 async def setup(bot: commands.Bot):
    await bot.add_cog(Magic8ball(bot))"""