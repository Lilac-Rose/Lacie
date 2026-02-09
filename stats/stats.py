import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
import sqlite3
import os
import json
import asyncio
import aiofiles
import re
from collections import Counter
from typing import Dict, List, Tuple

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "stats.db")

class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_id = 876772600704020530
        # Bot start time
        if not hasattr(self.bot, "start_time"):
            self.bot.start_time = datetime.now(timezone.utc)

        # Common words to exclude from word frequency analysis
        self.common_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 
            'with', 'by', 'as', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 
            'should', 'may', 'might', 'must', 'can', 'it', 'its', 'it\'s', 'i', 
            'you', 'he', 'she', 'they', 'we', 'me', 'him', 'her', 'them', 'us',
            'my', 'your', 'his', 'her', 'their', 'our', 'this', 'that', 'these',
            'those', 'am', 'not', 'so', 'too', 'very', 'just', 'now', 'then',
            'here', 'there', 'when', 'where', 'why', 'how', 'all', 'any', 'both',
            'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor',
            'only', 'own', 'same', 'than', 'too', 'very', 's', 't', 'don', 'don\'t', 'like',
            'pop',
            # URL-related words
            'http', 'https', 'www', 'com', 'org', 'net', 'io', 'gif', 'png', 'jpg',
            'jpeg', 'tenor', 'giphy', 'imgur', 'discord', 'cdn', 'media', 'attachments'
        }

        # Initialize the database
        self.init_db()
        
        # Stats file path (same directory as stats.py)
        self.stats_file = os.path.join(BASE_DIR, "bot_stats.json")
        
        # Start background task for stats file
        self.bot.loop.create_task(self.update_stats_file())

    # -----------------------------
    # Database methods
    # -----------------------------
    def init_db(self):
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        
        # Command usage table
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS command_usage (id INTEGER PRIMARY KEY, total INTEGER)"
        )
        cursor.execute("SELECT total FROM command_usage WHERE id=1")
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO command_usage (id, total) VALUES (1, 0)")
        
        # Message statistics tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_stats (
                channel_id INTEGER PRIMARY KEY,
                message_count INTEGER DEFAULT 0,
                last_updated TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_messages (
                date TEXT PRIMARY KEY,
                message_count INTEGER DEFAULT 0
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS word_frequency (
                word TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
        """)
        
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
    # Message statistics methods
    # -----------------------------
    async def record_message(self, message: discord.Message):
        """Record message statistics"""
        if message.guild is None or message.guild.id != self.guild_id:
            return
            
        if message.author.bot:
            return
            
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        
        # Update channel message count
        cursor.execute("""
            INSERT INTO message_stats (channel_id, message_count, last_updated)
            VALUES (?, 1, ?)
            ON CONFLICT(channel_id) DO UPDATE SET 
            message_count = message_count + 1,
            last_updated = ?
        """, (message.channel.id, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()))
        
        # Update daily message count
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        cursor.execute("""
            INSERT INTO daily_messages (date, message_count)
            VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET 
            message_count = message_count + 1
        """, (today,))
        
        # Update word frequency (only for messages with content)
        if message.content:
            words = self.extract_words(message.content)
            for word in words:
                if len(word) > 2 and word.lower() not in self.common_words:
                    cursor.execute("""
                        INSERT INTO word_frequency (word, count)
                        VALUES (?, 1)
                        ON CONFLICT(word) DO UPDATE SET 
                        count = count + 1
                    """, (word.lower(),))
        
        db.commit()
        db.close()

    def extract_words(self, text: str) -> List[str]:
        """Extract words from text, removing mentions, emojis, and URLs"""
        # Remove URLs first (more aggressive pattern)
        text = re.sub(r'https?://\S+', '', text)
        text = re.sub(r'www\.\S+', '', text)
        # Remove mentions
        text = re.sub(r'<@!?&?\d+>', '', text)
        # Remove channels
        text = re.sub(r'<#\d+>', '', text)
        # Remove emojis
        text = re.sub(r'<:\w+:\d+>', '', text)
        # Remove standalone domain-like patterns (e.g., "tenor.com", "giphy.gif")
        text = re.sub(r'\b\w+\.(com|org|net|io|gif|png|jpg|jpeg)\b', '', text, flags=re.IGNORECASE)
        # Remove punctuation
        text = re.sub(r'[^\w\s]', ' ', text)
        # Extract words
        words = re.findall(r'\b\w+\b', text.lower())
        return [word for word in words if len(word) > 2 and not self.is_url_segment(word)]

    def is_url_segment(self, word: str) -> bool:
        """Check if a word is likely part of a URL"""
        # Check if word contains common URL patterns
        url_patterns = [
            r'^\d+$',  # Pure numbers (often IDs in URLs)
            r'^[a-f0-9]{8,}$',  # Hex strings (often hashes in URLs)
        ]
        for pattern in url_patterns:
            if re.match(pattern, word):
                return True
        return False

    def get_most_active_channel(self) -> Tuple[str, int]:
        """Get the most active channel and its message count"""
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        cursor.execute("""
            SELECT channel_id, message_count 
            FROM message_stats 
            ORDER BY message_count DESC 
            LIMIT 1
        """)
        result = cursor.fetchone()
        db.close()
        
        if result:
            channel_id, count = result
            channel = self.bot.get_channel(channel_id)
            channel_name = f"#{channel.name}" if channel else f"Channel {channel_id}"
            return channel_name, count
        return "No data", 0

    def get_top_channels(self, limit: int = 10) -> List[Tuple[str, int]]:
        """Get top N most active channels"""
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        cursor.execute(f"""
            SELECT channel_id, message_count 
            FROM message_stats 
            ORDER BY message_count DESC 
            LIMIT {limit}
        """)
        results = cursor.fetchall()
        db.close()
        
        channel_stats = []
        for channel_id, count in results:
            channel = self.bot.get_channel(channel_id)
            channel_name = f"#{channel.name}" if channel else f"Unknown Channel"
            channel_stats.append((channel_name, count))
        
        return channel_stats

    def get_average_messages_per_day(self) -> float:
        """Calculate average messages per day"""
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        cursor.execute("SELECT SUM(message_count), COUNT(DISTINCT date) FROM daily_messages")
        result = cursor.fetchone()
        db.close()
        
        if result and result[1] > 0:
            total_messages, days_count = result
            return round(total_messages / days_count, 2)
        return 0.0

    def get_top_words(self, limit: int = 10) -> List[Tuple[str, int]]:
        """Get top N most common words"""
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        cursor.execute(f"""
            SELECT word, count 
            FROM word_frequency 
            ORDER BY count DESC 
            LIMIT {limit}
        """)
        results = cursor.fetchall()
        db.close()
        return results

    def get_total_messages(self) -> int:
        """Get total message count across all channels"""
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        cursor.execute("SELECT SUM(message_count) FROM message_stats")
        result = cursor.fetchone()
        db.close()
        return result[0] if result and result[0] else 0

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
        
        # Get message statistics
        most_active_channel, channel_msg_count = self.get_most_active_channel()
        avg_messages_per_day = self.get_average_messages_per_day()
        total_messages = self.get_total_messages()
        top_words = self.get_top_words(10)
        
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
            },
            'messageStats': {
                'totalMessages': total_messages,
                'mostActiveChannel': {
                    'name': most_active_channel,
                    'messageCount': channel_msg_count
                },
                'averageMessagesPerDay': avg_messages_per_day,
                'topWords': [{'word': word, 'count': count} for word, count in top_words]
            }
        }

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

    @commands.Cog.listener()
    async def on_message(self, message):
        await self.record_message(message)

    # -----------------------------
    # Discord slash command group
    # -----------------------------
    stats_group = app_commands.Group(name="stats", description="Server and bot statistics")

    @stats_group.command(name="server", description="Shows server and bot statistics")
    async def stats_server(self, interaction: discord.Interaction):
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
            color=self.bot.get_cog("EmbedColor").get_user_color(interaction.user),
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

    @stats_group.command(name="messages", description="Show message statistics")
    async def stats_messages(self, interaction: discord.Interaction):
        """Show detailed message statistics"""
        most_active_channel, channel_msg_count = self.get_most_active_channel()
        avg_messages_per_day = self.get_average_messages_per_day()
        total_messages = self.get_total_messages()
        
        embed = discord.Embed(
            title="📊 Message Statistics",
            color=self.bot.get_cog("EmbedColor").get_user_color(interaction.user),
            timestamp=datetime.now(timezone.utc)
        )
        
        # Overall stats
        embed.add_field(
            name="Overall Statistics",
            value=(
                f"**Total Messages:** {total_messages:,}\n"
                f"**Average Messages/Day:** {avg_messages_per_day}\n"
                f"**Most Active Channel:** {most_active_channel}\n"
                f"**Messages in Most Active:** {channel_msg_count:,}"
            ),
            inline=False
        )
        
        embed.set_footer(text="Use /stats channels for channel breakdown")
        await interaction.response.send_message(embed=embed)

    @stats_group.command(name="words", description="Show detailed word frequency statistics")
    async def stats_words(self, interaction: discord.Interaction):
        """Show top 10 most common words"""
        top_words = self.get_top_words(10)
        
        embed = discord.Embed(
            title="🔤 Word Frequency Statistics",
            color=self.bot.get_cog("EmbedColor").get_user_color(interaction.user),
            timestamp=datetime.now(timezone.utc)
        )
        
        if top_words:
            # Split into two columns for better readability
            half = len(top_words) // 2
            left_column = "\n".join([f"{i+1}. **{word}** - {count}" for i, (word, count) in enumerate(top_words[:half])])
            right_column = "\n".join([f"{i+half+1}. **{word}** - {count}" for i, (word, count) in enumerate(top_words[half:])])
            
            embed.add_field(name="Most Common Words", value=left_column, inline=True)
            embed.add_field(name="\u200b", value=right_column, inline=True)
        else:
            embed.description = "No word frequency data available yet. Start chatting to build up statistics!"
        
        embed.set_footer(text="Common words like 'the', 'and', etc. are excluded")
        await interaction.response.send_message(embed=embed)

    @stats_group.command(name="channels", description="Show most active channels")
    async def stats_channels(self, interaction: discord.Interaction):
        """Show top 10 most active channels"""
        top_channels = self.get_top_channels(10)
        
        embed = discord.Embed(
            title="📊 Most Active Channels",
            color=self.bot.get_cog("EmbedColor").get_user_color(interaction.user),
            timestamp=datetime.now(timezone.utc)
        )
        
        if top_channels:
            # Split into two columns
            half = len(top_channels) // 2
            left_column = "\n".join([f"{i+1}. **{channel}** - {count} msgs" for i, (channel, count) in enumerate(top_channels[:half])])
            right_column = "\n".join([f"{i+half+1}. **{channel}** - {count} msgs" for i, (channel, count) in enumerate(top_channels[half:])])
            
            embed.add_field(name="Top Channels", value=left_column, inline=True)
            if right_column:
                embed.add_field(name="\u200b", value=right_column, inline=True)
        else:
            embed.description = "No channel activity data available yet."
        
        total_messages = self.get_total_messages()
        embed.set_footer(text=f"Total messages tracked: {total_messages}")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot))