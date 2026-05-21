import discord
from discord import app_commands
from discord.ext import commands
import random


class RNG(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="rng", description="Generate a random number between two values")
    @app_commands.describe(minimum="The minimum value (inclusive)", maximum="The maximum value (inclusive)")
    async def rng(self, interaction: discord.Interaction, minimum: int, maximum: int):
        if minimum >= maximum:
            await interaction.response.send_message("Minimum must be less than maximum!", ephemeral=True)
            return

        result = random.randint(minimum, maximum)
        await interaction.response.send_message(f"🎲 **{result}** (between {minimum} and {maximum})")


async def setup(bot: commands.Bot):
    await bot.add_cog(RNG(bot))
