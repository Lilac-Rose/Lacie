import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
import sqlite3
import os
import aiohttp
from aiohttp import web
import json
import asyncio
import aiofiles

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "stats.db")

class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_id = 876772600704020530  # Your guild ID

        # Bot start time
        if not hasattr(self.bot, "start_time"):
            self.bot.start_time = datetime.now(timezone.utc)

        # Initialize the database
        self.init_db()
        
        # Stats file path (same directory as stats.py)
        self.stats_file = os.path.join(BASE_DIR, "bot_stats.json")
        
        # Start background tasks
        self.bot.loop.create_task(self.update_stats_file())
        self.bot.loop.create_task(self.start_mini_api())

    # -----------------------------
    # Database methods
    # -----------------------------
    def init_db(self):
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS command_usage (id INTEGER PRIMARY KEY, total INTEGER)"
        )
        cursor.execute("SELECT total FROM command_usage WHERE id=1")
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO command_usage (id, total) VALUES (1, 0)")
        db.commit()
        db.close()

    def increment_usage(self):
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        cursor.execute("UPDATE command_usage SET total = total + 1 WHERE id=1")
        db.commit()
        db.close()

    def get_usage(self):
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        cursor.execute("SELECT total FROM command_usage WHERE id=1")
        total = cursor.fetchone()[0]
        db.close()
        return total

    # -----------------------------
    # Stats file management
    # -----------------------------
    async def cleanup_old_stats_files(self):
        """Remove any old stats files to prevent accumulation"""
        try:
            stats_dir = BASE_DIR
            for filename in os.listdir(stats_dir):
                if filename.startswith("bot_stats") and filename.endswith(".json"):
                    file_path = os.path.join(stats_dir, filename)
                    # Keep only the current stats file
                    if file_path != self.stats_file:
                        os.remove(file_path)
                        print(f"Removed old stats file: {filename}")
        except Exception as e:
            print(f"Error cleaning up old stats files: {e}")

    async def update_stats_file(self):
        """Update stats JSON file every 30 seconds"""
        await self.bot.wait_until_ready()
        
        # Clean up old files on startup
        await self.cleanup_old_stats_files()
        
        while not self.bot.is_closed():
            try:
                stats = await self.gather_stats()
                async with aiofiles.open(self.stats_file, 'w') as f:
                    await f.write(json.dumps(stats, indent=2, default=str))
            except Exception as e:
                print(f"Error updating stats file: {e}")
            
            await asyncio.sleep(30)  # Update every 30 seconds

    async def gather_stats(self):
        """Gather real-time statistics"""
        guild = self.bot.get_guild(self.guild_id)
        
        if not guild:
            return {'error': 'Guild not found', 'guild_id': self.guild_id}
        
        # Calculate uptime
        uptime = datetime.now(timezone.utc) - self.bot.start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        # Count channels
        text_channels = len([c for c in guild.channels if isinstance(c, discord.TextChannel)])
        voice_channels = len([c for c in guild.channels if isinstance(c, discord.VoiceChannel)])
        categories = len([c for c in guild.channels if isinstance(c, discord.CategoryChannel)])
        
        return {
            'server': {
                'memberCount': guild.member_count,
                'createdDate': guild.created_at.strftime('%b %d, %Y'),
                'textChannels': text_channels,
                'voiceChannels': voice_channels,
                'categories': categories,
                'boostLevel': guild.premium_tier,
                'boostCount': guild.premium_subscription_count,
                'iconUrl': str(guild.icon.url) if guild.icon else None,
                'bannerUrl': str(guild.banner.url) if guild.banner else None,
                'guildName': guild.name
            },
            'bot': {
                'uptime': f"{hours}h {minutes}m {seconds}s",
                'totalCommands': self.get_usage(),
                'serverCount': len(self.bot.guilds),
                'botUsers': len(self.bot.users),
                'latency': round(self.bot.latency * 1000),
                'developer': 'Lilac Aria Rose',
                'lastUpdated': datetime.now(timezone.utc).isoformat()
            }
        }

    # -----------------------------
    # Mini API Server
    # -----------------------------
    async def start_mini_api(self):
        """Start a simple HTTP server for real-time stats"""
        await self.bot.wait_until_ready()
        
        app = web.Application()
        
        async def handle_stats(request):
            stats = await self.gather_stats()
            return web.json_response(stats)
        
        app.router.add_get('/stats', handle_stats)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', 8765)
        await site.start()
        print("Bot stats API running on port 8765")

    # -----------------------------
    # Discord event listeners
    # -----------------------------
    @commands.Cog.listener()
    async def on_command(self, ctx):
        self.increment_usage()

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        # Only count application commands (slash commands)
        if interaction.type == discord.InteractionType.application_command:
            self.increment_usage()

    # -----------------------------
    # Discord slash command
    # -----------------------------
    @app_commands.command(name="stats", description="Shows server and bot statistics")
    async def stats(self, interaction: discord.Interaction):
        guild = interaction.guild

        # Bot uptime
        uptime = datetime.now(timezone.utc) - self.bot.start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        # Total commands
        total_commands = self.get_usage()

        # Count channels separately
        text_channels = len([c for c in guild.channels if isinstance(c, discord.TextChannel)])
        voice_channels = len([c for c in guild.channels if isinstance(c, discord.VoiceChannel)])
        categories = len([c for c in guild.channels if isinstance(c, discord.CategoryChannel)])

        # Embed
        embed = discord.Embed(
            title=f"🌟 {guild.name} Statistics 🌟",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc)
        )

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if guild.banner:
            embed.set_image(url=guild.banner.url)

        # Server stats grid
        embed.add_field(name="👥 Members", value=f"**{guild.member_count}**", inline=True)
        embed.add_field(name="📅 Created On", value=f"**{guild.created_at.strftime('%b %d, %Y')}**", inline=True)
        embed.add_field(name="💬 Text Channels", value=f"**{text_channels}**", inline=True)
        embed.add_field(name="🔊 Voice Channels", value=f"**{voice_channels}**", inline=True)
        embed.add_field(name="📂 Categories", value=f"**{categories}**", inline=True)
        embed.add_field(name="🚀 Boost Level", value=f"**{guild.premium_tier}**", inline=True)
        embed.add_field(name="✨ Boosts", value=f"**{guild.premium_subscription_count}**", inline=True)

        embed.add_field(name="\u200b", value="\u200b", inline=False)

        # Bot stats
        embed.add_field(
            name="🤖 Bot Stats",
            value=(
                f"**Developer:** Lilac Aria Rose\n"
                f"**Uptime:** {uptime_str}\n"
                f"**Total Commands Used:** {total_commands}\n"
                f"**Servers:** {len(self.bot.guilds)}\n"
                f"**Bot Users:** {len(self.bot.users)}"
            ),
            inline=False
        )

        embed.set_footer(text=f"Server ID: {guild.id}")

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot))