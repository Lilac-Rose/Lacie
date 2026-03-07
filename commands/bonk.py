import discord
from discord import app_commands
from discord.ext import commands
import os
from pathlib import Path

class Bonk(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # resolve path at init so we're not doing it on every command call
        self.bonk_path = Path(__file__).parent.parent / "media" / "kat_bonk.png"

    @app_commands.command(name="bonk", description="Bonk another user!")
    @app_commands.describe(user="The user you want to bonk")
    async def bonk(self, interaction: discord.Interaction, user: discord.User):
        try:
            # defer because we're sending a file attachment
            await interaction.response.defer(thinking=True)

            if not os.path.exists(self.bonk_path):
                await interaction.followup.send("Bonk image not found!", ephemeral=True)
                return

            # no self-bonking
            if user.id == interaction.user.id:
                await interaction.followup.send("You cannot bonk yourself silly", ephemeral=False)
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
