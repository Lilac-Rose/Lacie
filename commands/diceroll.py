import discord
from discord.ext import commands
from discord import app_commands
import random
import re

class DiceRoll(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="diceroll", description="Roll dice, supported die are d4, d6, d8, d10, d12, d20, d100")
    @app_commands.describe(dice="Enter your roll (e.g., d20, 2d6+3, 3d8-2)")
    async def diceroll(self, interaction: discord.Interaction, dice: str):
        pattern = r"^(\d*)d(\d+)([+-]\d+)?$"
        match = re.match(pattern, dice.replace(" ", "").lower())

        if not match:
            await interaction.response.send_message("Invalid format!", ephemeral=True)
            return
    
        num_dice = int(match.group(1)) if match.group(1) else 1
        sides = int(match.group(2))
        modifier = int(match.group(3)) if match.group(3) else 0

        allowed_sides = [4, 6, 8, 10, 12, 20 ,100]
        if sides not in allowed_sides:
            await interaction.response.send_message("Unsupported die! Allowed dice are: d4, d6, d8, d10, d12, d20, d100", ephemeral=True)
            return
        
        if num_dice < 1 or num_dice > 100:
            await interaction.response.send_message("You can only roll between 1 and 100 die at once.", ephemeral=True)
            return
        
        rolls = [random.randint(1, sides) for _ in range(num_dice)]
        total = sum(rolls) + modifier

        dice_str = ", ".join(map(str, rolls))
        mod_str = f"{modifier:+}" if modifier else ""
        result_str = (
            f"You rolled **{num_dice}d{sides}{mod_str}**\n"
            f"→ Rolls: {dice_str}\n"
            f"**Total: {total}**"
        )

        await interaction.response.send_message(result_str)

async def setup(bot):
    await bot.add_cog(DiceRoll(bot))