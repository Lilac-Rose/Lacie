"""
Archipelago Monitor Cog
Monitors an Archipelago server log file and sends Discord notifications
when items are sent between players.
"""

import discord
from discord.ext import commands, tasks
import asyncio
import re
import os
from dotenv import load_dotenv
from typing import Optional, Set
from pathlib import Path
from utils.logger import get_logger

load_dotenv()

logger = get_logger(__name__)


class ArchipelagoMonitor(commands.Cog):
    """Monitors Archipelago multiworld log file and posts updates to Discord."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        # Get configuration from environment variables
        self.channel_id = int(os.getenv("ARCHIPELAGO_CHANNEL_ID", "0"))
        self.log_directory = os.getenv("ARCHIPELAGO_LOG_DIR", "/home/lilacrose/Archipelago/logs")
        self.enabled = os.getenv("ARCHIPELAGO_ENABLED", "false").lower() == "true"
        
        self.notification_channel: Optional[discord.TextChannel] = None
        self.current_log_file: Optional[Path] = None
        self.last_position = 0  # Track where we last read in the file
        self.seen_lines: Set[str] = set()  # Track lines we've already processed
        
        # Regex patterns for parsing log messages
        self.patterns = {
            'item_send': re.compile(r'\(Team #\d+\) (.+?) sent (.+?) to (.+?) \((.+?)\)'),
            'join': re.compile(r'Notice \(all\): (.+?) \(Team #\d+\) (?:playing|tracking) (.+?) has joined'),
            'leave': re.compile(r'Notice \(all\): (.+?) \(Team #\d+\) has (?:left the game|stopped tracking)'),
            'tag_change': re.compile(r'Notice \(all\): (.+?) \(Team #\d+\) has changed tags from \[.*?\] to \[(.+?)\]'),
            'server_start': re.compile(r'Hosting game at (.+?) \(Password: (.+?)\)'),
        }
        
        logger.info(f"Initializing log monitor - Enabled: {self.enabled}, Channel: {self.channel_id}, Log dir: {self.log_directory}")

        if self.enabled and self.channel_id:
            logger.info("Monitor will start when bot is ready")
            self.monitor_log.start()
        else:
            if not self.enabled:
                logger.info("Monitor DISABLED: ARCHIPELAGO_ENABLED is not true")
            if not self.channel_id:
                logger.info("Monitor DISABLED: ARCHIPELAGO_CHANNEL_ID is not set")
    
    async def cog_unload(self):
        """Called when the cog is unloaded."""
        self.monitor_log.cancel()
    
    def get_most_recent_log_file(self) -> Optional[Path]:
        """Find the most recent Server_*.txt log file in the logs directory."""
        try:
            log_dir = Path(self.log_directory)
            if not log_dir.exists():
                logger.error(f"Log directory does not exist: {self.log_directory}")
                return None
            
            # Find all Server_*.txt files
            log_files = list(log_dir.glob("Server_*.txt"))
            
            if not log_files:
                logger.warning(f"No Server_*.txt log files found in {self.log_directory}")
                return None
            
            # Get the most recently modified file
            most_recent = max(log_files, key=lambda p: p.stat().st_mtime)
            logger.info(f"Found most recent log file: {most_recent.name}")
            return most_recent
            
        except Exception as e:
            logger.error(f"Error finding log file: {e}")
            return None
    
    @tasks.loop(seconds=2)
    async def monitor_log(self):
        """Monitor the Archipelago log file for new events."""
        try:
            # Check if we need to find a new log file (first run or file changed)
            most_recent = self.get_most_recent_log_file()
            
            if most_recent is None:
                logger.debug(f"No log file found in {self.log_directory}")
                return
            
            # If this is a different file than we're currently reading, switch to it
            if self.current_log_file != most_recent:
                logger.info(f"Switching to new log file: {most_recent.name}")
                self.current_log_file = most_recent
                self.last_position = 0
                
                # Notify Discord that we're reading a new log
                if self.notification_channel:
                    await self.notification_channel.send(f"📄 Now monitoring: `{most_recent.name}`")
            
            # Check if file exists
            if not self.current_log_file.exists():
                logger.debug(f"Log file not found: {self.current_log_file}")
                return
            
            # Read new lines from the file
            with open(self.current_log_file, 'r', encoding='utf-8') as f:
                # Seek to last position
                f.seek(self.last_position)
                
                # Read new lines
                new_lines = f.readlines()
                
                # Update position
                self.last_position = f.tell()
            
            # Process each new line
            for line in new_lines:
                line = line.strip()
                if not line:
                    continue
                
                # Skip if we've already processed this line
                if line in self.seen_lines:
                    continue
                
                self.seen_lines.add(line)
                
                # Keep seen_lines from growing too large
                if len(self.seen_lines) > 1000:
                    # Remove oldest half
                    self.seen_lines = set(list(self.seen_lines)[-500:])
                
                # Try to parse and handle the line
                await self.process_log_line(line)
                
        except Exception as e:
            logger.error(f"Error monitoring log file: {e}")
    
    @monitor_log.before_loop
    async def before_monitor(self):
        """Wait until the bot is ready before starting the monitor."""
        await self.bot.wait_until_ready()
        
        # Get the notification channel
        self.notification_channel = self.bot.get_channel(self.channel_id)
        if self.notification_channel:
            logger.info(f"Notification channel set to: {self.notification_channel.name}")
            
            # Find the most recent log file
            most_recent = self.get_most_recent_log_file()
            
            if most_recent:
                self.current_log_file = most_recent
                
                # Set position to end of file (don't process old messages)
                with open(most_recent, 'r', encoding='utf-8') as f:
                    f.seek(0, 2)  # Seek to end
                    self.last_position = f.tell()
                
                await self.notification_channel.send(
                    f"🎮 Archipelago log monitor started!\n"
                    f"📄 Monitoring: `{most_recent.name}`"
                )
            else:
                await self.notification_channel.send(
                    f"⚠️ No Archipelago log files found in: `{self.log_directory}`\n"
                    f"Waiting for server to start..."
                )
                logger.warning(f"No log files found in: {self.log_directory}")
        else:
            logger.error(f"Could not find channel with ID {self.channel_id}")
    
    async def process_log_line(self, line: str):
        """Process a single log line and send notifications if needed."""
        if not self.notification_channel:
            return
        
        try:
            # Check for item send
            match = self.patterns['item_send'].search(line)
            if match:
                sender = match.group(1)
                item = match.group(2)
                receiver = match.group(3)
                location = match.group(4)
                await self.handle_item_send(sender, item, receiver, location)
                return
            
            # Check for player join
            match = self.patterns['join'].search(line)
            if match:
                player = match.group(1)
                game = match.group(2)
                await self.handle_join(player, game)
                return
            
            # Check for player leave
            match = self.patterns['leave'].search(line)
            if match:
                player = match.group(1)
                await self.handle_leave(player)
                return
            
            # Check for tag changes (DeathLink, etc.)
            match = self.patterns['tag_change'].search(line)
            if match:
                player = match.group(1)
                tags = match.group(2)
                await self.handle_tag_change(player, tags)
                return
            
            # Check for server start
            match = self.patterns['server_start'].search(line)
            if match:
                address = match.group(1)
                password = match.group(2)
                await self.handle_server_start(address, password)
                return
            
        except Exception as e:
            logger.error(f"Error processing line: {line}")
            logger.error(f"Error: {e}")
    
    async def handle_item_send(self, sender: str, item: str, receiver: str, location: str):
        """Handle an item send notification."""
        # Clean up item name (remove underscores, make readable)
        item_display = item.replace('_', ' ')
        location_display = location.replace('_', ' ')
        
        embed = discord.Embed(
            title="📦 Item Sent!",
            color=discord.Color.green()
        )
        
        embed.add_field(name="Item", value=item_display, inline=False)
        embed.add_field(name="From", value=sender, inline=True)
        embed.add_field(name="To", value=receiver, inline=True)
        embed.add_field(name="Location", value=location_display, inline=False)
        
        try:
            await self.notification_channel.send(embed=embed)
            logger.info(f"Item send: {sender} sent {item} to {receiver} at {location}")
        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")
    
    async def handle_join(self, player: str, game: str):
        """Handle a player join notification."""
        # Clean up game name
        game_display = game.replace('_', ' ')
        
        embed = discord.Embed(
            description=f"👋 **{player}** joined playing **{game_display}**",
            color=discord.Color.blue()
        )
        
        try:
            await self.notification_channel.send(embed=embed)
            logger.info(f"Player join: {player} playing {game}")
        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")
    
    async def handle_leave(self, player: str):
        """Handle a player disconnect notification."""
        embed = discord.Embed(
            description=f"👋 **{player}** left the game",
            color=discord.Color.greyple()
        )
        
        try:
            await self.notification_channel.send(embed=embed)
            logger.info(f"Player leave: {player}")
        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")
    
    async def handle_tag_change(self, player: str, tags: str):
        """Handle a tag change notification (like enabling DeathLink)."""
        # Only notify for interesting tags
        if 'DeathLink' in tags:
            embed = discord.Embed(
                description=f"💀 **{player}** enabled **DeathLink**",
                color=discord.Color.dark_red()
            )
            
            try:
                await self.notification_channel.send(embed=embed)
                logger.info(f"Tag change: {player} -> {tags}")
            except Exception as e:
                logger.error(f"Failed to send Discord message: {e}")
    
    async def handle_server_start(self, address: str, password: str):
        """Handle server start notification."""
        embed = discord.Embed(
            title="🎮 Archipelago Server Started",
            color=discord.Color.green()
        )
        
        embed.add_field(name="Address", value=address, inline=False)
        
        # Only show password if it's not sensitive
        if password and password != "None":
            embed.add_field(name="Password", value=password, inline=False)
        
        try:
            await self.notification_channel.send(embed=embed)
            logger.info(f"Server started at {address}")
        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")


async def setup(bot: commands.Bot):
    """Setup function to add the cog to the bot."""
    await bot.add_cog(ArchipelagoMonitor(bot))