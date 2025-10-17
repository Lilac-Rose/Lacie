import discord
from discord import app_commands
from discord.ext import commands
import os

class Bonk(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bonk_path = os.path.join(os.path.dirname(__file__), "..", "media", "kat_bonk.png")

    @app_commands.command(name="bonk", description="Bonk another user!")
    @app_commands.describe(user="The user you want to bonk")
    async def bonk(self, interaction: discord.Interaction, user: discord.User):
        try:
            await interaction.response.defer(thinking=True)

            if not os.path.exists(self.bonk_path):
                await interaction.followup.send("Bonk image not found!", ephemeral=True)
                return
            
            file = discord.File(self.bonk_path, filename="bonk.png")
            await interaction.followup.send(
                f"{user.mention} has been bonked by {interaction.user.mention}. Bonk!",
                file=file
            )

        except Exception as e:
            await interaction.followup.send("An error occurred while processing the bonk.", ephemeral=True)
            raise e
async def setup(bot: commands.Bot):
    await bot.add_cog(Bonk(bot))