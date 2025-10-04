import discord
from discord.ext import commands
from discord import app_commands

class SparkleInfo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="sparkleinfo", description="Learn about sparkles and how they work")
    async def sparkleinfo(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="✨ Sparkles ✨",
            description=(
                "Sparkles are **random reactions** that can appear on messages! "
                "Sometimes, when you send a message, you might get a sparkle reaction and a little notification.\n\n"
                "**Types of Sparkles:**\n"
                "💫 **Regular Sparkle** – Appears randomly (1/1,000 chance per message)\n"
                "🌟 **Rare Sparkle** – Appears less often (1/10,000 chance per message)\n"
                "✨ **Epic Sparkle** – Extremely rare! (1/100,000 chance per message)\n\n"
                "You can track your sparkles and compare with others using `/sparkleleaderboard`."
            ),
            color=discord.Color.purple()
        )
        embed.set_footer(text="Keep sending messages to try your luck!")
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(SparkleInfo(bot))
