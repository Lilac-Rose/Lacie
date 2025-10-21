import discord
from discord.ext import commands
from discord import app_commands
import time
import aiosqlite
import os

class Ping(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = os.path.join(os.path.dirname(__file__), "suggestions.db")

    @app_commands.command(name="ping", description="Check the bot's latency")
    async def ping(self, interaction: discord.Interaction):
        start_time = time.perf_counter()
        await interaction.response.send_message("Pinging...")
        end_time = time.perf_counter()
        api_latency = round((end_time - start_time) * 1000)

        ws_latency = round(self.bot.latency * 1000)

        # Measure database latency
        db_start = time.perf_counter()
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("SELECT 1")
                await db.commit()
        except Exception:
            db_latency = "Error"
        else:
            db_end = time.perf_counter()
            db_latency = round((db_end - db_start) * 1000)

        embed = discord.Embed(
            title="Pong!",
            color=discord.Color.green()
        )
        embed.add_field(name="WebSocket Latency", value=f"{ws_latency}ms", inline=True)
        embed.add_field(name="API Latency", value=f"{api_latency}ms", inline=True)
        embed.add_field(name="Database Latency", value=f"{db_latency}ms", inline=True)

        await interaction.edit_original_response(content=None, embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Ping(bot))
