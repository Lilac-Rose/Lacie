import discord
from discord.ext import commands
from discord import app_commands
import random

class Meow(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="meow")
    async def ping(self, interaction: discord.Interaction):

        meow_list=["Meowwwww~", "Purrrrrr", "Nyaaaaaa", "Meow Meow", "Nya!", "Meow :3"]
        meow_index = random.randrange(0,5)
        await interaction.response.send_message(meow_list[meow_index])

async def setup(bot: commands.Bot):
    await bot.add_cog(Meow(bot))