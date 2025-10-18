import discord
from discord.ext import commands
from discord import app_commands
import time

class Ping(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @app_commands.command(name="ping", description="Check the bot's latency")
    async def ping(self, interaction: discord.Interaction):
        # Measure API latency (time to respond to the interaction)
        start_time = time.perf_counter()
        await interaction.response.send_message("Pinging...")
        end_time = time.perf_counter()
        api_latency = round((end_time - start_time) * 1000)
        
        # Get WebSocket latency
        ws_latency = round(self.bot.latency * 1000)
        
        # Edit the message with the results
        embed = discord.Embed(
            title="Pong!",
            color=discord.Color.green()
        )
        embed.add_field(name="WebSocket Latency", value=f"{ws_latency}ms", inline=True)
        embed.add_field(name="API Latency", value=f"{api_latency}ms", inline=True)
        
        await interaction.edit_original_response(content=None, embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Ping(bot))