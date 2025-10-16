import discord
from discord.ext import commands
from discord import app_commands

class Meow(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="meow")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message("Meowwwww~")

async def setup(bot: commands.Bot):
    await bot.add_cog(Meow(bot))