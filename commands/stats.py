import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
import sqlite3
import os

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "stats.db")


class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Bot start time
        if not hasattr(self.bot, "start_time"):
            self.bot.start_time = datetime.now(timezone.utc)

        # Initialize the database
        self.init_db()

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
    # Prefix command listener
    # -----------------------------
    @commands.Cog.listener()
    async def on_command(self, ctx):
        self.increment_usage()

    # -----------------------------
    # Slash command listener
    # -----------------------------
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        # Only count application commands (slash commands)
        if interaction.type == discord.InteractionType.application_command:
            self.increment_usage()

    # -----------------------------
    # Slash command
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