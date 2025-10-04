import discord
from discord.ext import commands
from discord import app_commands

class WordBombInfo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="wordbombinfo", description="Learn how the Word Bomb game works")
    async def wordbombinfo(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="💣 Word Bomb Info",
            color=discord.Color.orange(),
            description=(
                "Word Bomb is a fast-paced word game in this server! 📝\n\n"
                "**How to Play:**\n"
                "• A substring will appear in the channel.\n"
                "• Type a word containing that substring as fast as you can.\n"
                "• Each correct word gives you points!\n"
                "• The game will then generate a new substring for the next round.\n\n"
                "**Commands:**\n"
                "• `/start` – Start a new Word Bomb game (Admin only)\n"
                "• `/end` – End the current game (Admin only)\n"
                "• `/score [user]` – Check your or another user's score\n"
                "• `/wordbomb_leaderboard` – Show top players in the server\n\n"
                "Have fun and try to climb the leaderboard! 🏆"
            )
        )
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(WordBombInfo(bot))
