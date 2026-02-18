import discord
from discord.ext import commands
from discord import app_commands
import random

MEOW_LIST = ["Meowwwww~", "Purrrrrr", "Nyaaaaaa", "Meow Meow", "Nya!", "Meow :3"]

class Meow(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="meow")
    async def meow(self, interaction: discord.Interaction):
        meow_index = random.randrange(0, len(MEOW_LIST))
        await interaction.response.send_message(MEOW_LIST[meow_index])

async def setup(bot: commands.Bot):
    await bot.add_cog(Meow(bot))