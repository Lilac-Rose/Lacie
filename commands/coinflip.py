import discord
from discord.ext import commands
from discord import app_commands
import random

class Coinflip(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="coinflip")
    async def coinflip(self, interaction: discord.Interaction):

        coin = random.randrange(0,2)
        if coin == 1:
            await interaction.response.send_message("Heads!")
        elif coin == 0:
            await interaction.response.send_message("Tails!")

async def setup(bot: commands.Bot):
    await bot.add_cog(Coinflip(bot))