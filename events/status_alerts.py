import discord
from discord.ext import commands, tasks
import sqlite3
import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from utils.logger import get_logger

logger = get_logger(__name__)

class StatusMonitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = Path("/home/lilacrose/lilacrose.dev2.0/monitor.db")
        self.admin_user_id = 252130669919076352
        self.last_status = {}
        self.check_status.start()
    
    def cog_unload(self):
        """Stop the monitoring loop when cog is unloaded"""
        self.check_status.cancel()
    
    @tasks.loop(minutes=1)
    async def check_status(self):
        """Check service status every minute"""
        try:
            if not self.db_path.exists():
                return

            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            cur.execute("""
                SELECT service_name, status, error_message, timestamp
                FROM service_checks
                WHERE id IN (
                    SELECT MAX(id)
                    FROM service_checks
                    GROUP BY service_name
                )
            """)
            
            current_statuses = {row['service_name']: row for row in cur.fetchall()}
            conn.close()
            
            admin = await self.bot.fetch_user(self.admin_user_id)
            if not admin:
                return
            
            for service_name, row in current_statuses.items():
                current_status = row['status']
                error_msg = row['error_message']
                
                service_display_names = {
                    "website": "TERMINAL//FKLR-F23",
                    "game_tracker": "GAME_TRACKER//FKLR-F23",
                    "forms_server": "Lacie Bot Website",
                    "file_server": "File Server",
                    "discord_bot": "Lacie Bot"
                }
                display_name = service_display_names.get(service_name, service_name)
                
                # If we haven't seen this service before, just store it
                if service_name not in self.last_status:
                    self.last_status[service_name] = current_status
                    continue
                
                previous_status = self.last_status[service_name]
                
                # Service went DOWN
                if current_status == "down" and previous_status != "down":
                    embed = discord.Embed(
                        title="🔴 Service Down Alert",
                        description=f"**{display_name}** has gone offline",
                        color=discord.Color.red(),
                        timestamp=datetime.now(ZoneInfo("America/New_York"))
                    )
                    if error_msg:
                        embed.add_field(name="Error", value=f"```{error_msg}```", inline=False)
                    embed.add_field(name="Service ID", value=f"`{service_name}`", inline=True)
                    embed.set_footer(text="Status Monitor Alert")
                    
                    try:
                        await admin.send(embed=embed)
                    except Exception as e:
                        logger.error(f"Failed to send down alert for {service_name}: {e}")
                
                # Service went DEGRADED
                elif current_status == "degraded" and previous_status == "up":
                    embed = discord.Embed(
                        title="⚠️ Service Degraded",
                        description=f"**{display_name}** is experiencing issues",
                        color=discord.Color.orange(),
                        timestamp=datetime.now(ZoneInfo("America/New_York"))
                    )
                    if error_msg:
                        embed.add_field(name="Error", value=f"```{error_msg}```", inline=False)
                    embed.add_field(name="Service ID", value=f"`{service_name}`", inline=True)
                    embed.set_footer(text="Status Monitor Alert")
                    
                    try:
                        await admin.send(embed=embed)
                    except Exception as e:
                        logger.error(f"Failed to send degraded alert for {service_name}: {e}")
                
                # Service RECOVERED
                elif current_status == "up" and previous_status in ["down", "degraded"]:
                    # Calculate downtime
                    conn = sqlite3.connect(self.db_path)
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    
                    cur.execute("""
                        SELECT started_at, ended_at, duration_seconds
                        FROM downtime_incidents
                        WHERE service_name = ? AND ended_at IS NOT NULL
                        ORDER BY id DESC LIMIT 1
                    """, (service_name,))
                    
                    incident = cur.fetchone()
                    conn.close()
                    
                    embed = discord.Embed(
                        title="✅ Service Recovered",
                        description=f"**{display_name}** is back online",
                        color=discord.Color.green(),
                        timestamp=datetime.now(ZoneInfo("America/New_York"))
                    )
                    
                    if incident and incident['duration_seconds']:
                        duration = incident['duration_seconds']
                        if duration < 60:
                            duration_str = f"{int(duration)} seconds"
                        elif duration < 3600:
                            duration_str = f"{int(duration / 60)} minutes"
                        else:
                            duration_str = f"{duration / 3600:.1f} hours"
                        embed.add_field(name="Downtime", value=duration_str, inline=True)
                    
                    embed.add_field(name="Service ID", value=f"`{service_name}`", inline=True)
                    embed.set_footer(text="Status Monitor Alert")
                    
                    try:
                        await admin.send(embed=embed)
                    except Exception as e:
                        logger.error(f"Failed to send recovery alert for {service_name}: {e}")
                
                # Update last known status
                self.last_status[service_name] = current_status
                
        except Exception as e:
            logger.error(f"Error checking status: {e}", exc_info=True)
    
    @check_status.before_loop
    async def before_check_status(self):
        """Wait for bot to be ready before starting the loop"""
        await self.bot.wait_until_ready()
        logger.info("Starting status monitoring loop...")

        # Initialize last_status with current state on startup
        try:
            if self.db_path.exists():
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                
                cur.execute("""
                    SELECT service_name, status
                    FROM service_checks
                    WHERE id IN (
                        SELECT MAX(id)
                        FROM service_checks
                        GROUP BY service_name
                    )
                """)
                
                for row in cur.fetchall():
                    self.last_status[row['service_name']] = row['status']
                
                conn.close()
                logger.info(f"Initialized with {len(self.last_status)} services")
        except Exception as e:
            logger.error(f"Failed to initialize: {e}", exc_info=True)
    
    @commands.command(name="statustest")
    @commands.is_owner()
    async def status_test(self, ctx):
        """Test the status monitoring alerts (Owner only)"""
        embed = discord.Embed(
            title="🔔 Status Monitor Test",
            description="This is a test alert from the status monitoring system",
            color=discord.Color.blue(),
            timestamp=datetime.now(ZoneInfo("America/New_York"))
        )
        embed.add_field(name="Database Path", value=f"`{self.db_path}`", inline=False)
        embed.add_field(name="Database Exists", value="✅ Yes" if self.db_path.exists() else "❌ No", inline=True)
        embed.add_field(name="Monitoring", value=f"{len(self.last_status)} services", inline=True)
        embed.add_field(name="Admin User ID", value=f"`{self.admin_user_id}`", inline=True)
        
        if self.last_status:
            status_list = "\n".join([f"• `{name}`: {status}" for name, status in self.last_status.items()])
            embed.add_field(name="Current Status", value=status_list, inline=False)
        
        await ctx.send(embed=embed)
        
        # Try to DM the admin
        try:
            admin = await self.bot.fetch_user(self.admin_user_id)
            test_embed = discord.Embed(
                title="✅ DM Test Successful",
                description="If you're seeing this, status alerts will work!",
                color=discord.Color.green()
            )
            await admin.send(embed=test_embed)
            await ctx.send("✅ Test DM sent successfully!")
        except Exception as e:
            await ctx.send(f"❌ Failed to send test DM: {e}")

async def setup(bot):
    await bot.add_cog(StatusMonitor(bot))