import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import pytz
from moderation.loader import ModerationBase
from .groups import xp_admin_group
from utils.logger import get_logger

logger = get_logger(__name__)

BACKUP_CHANNEL_ID = 946421558778417172
NOTIFICATION_CHANNEL_ID = 1424145004976275617
BACKUP_INTERVAL = timedelta(days=1)  # Daily backups
MAX_BACKUP_AGE = timedelta(days=30)  # Keep backups for 30 days
EST = pytz.timezone('America/New_York')
BACKUP_HOUR = 10  # 10 AM EST

class BackupXP(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_dir = Path(__file__).parent.parent / "data"
        self.backup_dir = Path(__file__).parent.parent / "data" / "backups" / "xp"
        self.last_backup_file = self.backup_dir / "last_backup.txt"
        self.last_auto_backup_file = self.backup_dir / "last_auto_backup.txt"
        os.makedirs(self.backup_dir, exist_ok=True)
        # Register the manual backup command onto the shared xpadmin group
        xp_admin_group.add_command(app_commands.command(name="backup", description="Backup both lifetime and annual XP databases")(self.backup_xp))
        # Start the daily check task
        self.auto_backup_task.start()
    
    async def cog_load(self):
        """Check on startup if a backup is due"""
        # Get current time in EST
        now_est = datetime.now(EST)
        
        # Only check for backup if it's 10 AM EST
        if now_est.hour == BACKUP_HOUR:
            await self.check_last_backup()
    
    def cog_unload(self):
        self.auto_backup_task.cancel()
        xp_admin_group.remove_command("backup")
    
    @ModerationBase.is_admin()
    async def backup_xp(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        success, message = await self.create_backup()
        await interaction.followup.send(message)
    
    @tasks.loop(minutes=15)
    async def auto_backup_task(self):
        """Runs every 15 minutes and checks if it's 10 AM EST and a daily backup is due"""
        # Get current time in EST
        now_est = datetime.now(EST)
        
        logger.debug(f"Time check: {now_est.strftime('%Y-%m-%d %I:%M %p %Z')} (Hour: {now_est.hour}, Minute: {now_est.minute})")

        # Check if it's between 10:00 AM and 10:15 AM EST
        if now_est.hour == BACKUP_HOUR and now_est.minute < 15:
            logger.debug("Inside backup window - Checking for backup")
            await self.check_last_backup()
        else:
            logger.debug(f"Outside backup window (need hour={BACKUP_HOUR} and minute<15)")
    
    @auto_backup_task.before_loop
    async def before_auto_backup(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()
        logger.info("Auto backup task started. Will check every 15 minutes for 10 AM EST backup window.")
        now_est = datetime.now(EST)
        logger.info(f"Current time: {now_est.strftime('%Y-%m-%d %I:%M %p %Z')}")
    
    async def check_last_backup(self):
        """Check if an auto backup has been done today at 10 AM EST"""
        now = datetime.now()
        now_est = datetime.now(EST)
        
        logger.info(f"Checking auto backup status at {now_est.strftime('%Y-%m-%d %I:%M %p %Z')}")

        if not os.path.exists(self.last_auto_backup_file):
            # No previous auto backup — make initial backup
            logger.info("No last_auto_backup.txt found, creating initial auto backup")
            await self.create_backup(log_channel=True, reason="Auto daily backup (10 AM EST)", is_auto=True)
            await self.cleanup_old_backups()
            return
        
        with open(self.last_auto_backup_file, "r") as f:
            try:
                last_time = datetime.fromisoformat(f.read().strip())
            except Exception:
                last_time = datetime.min
        
        # Check if we've already done an auto backup today
        last_time_est = last_time.astimezone(EST)
        logger.info(f"Last auto backup: {last_time_est.strftime('%Y-%m-%d %I:%M %p %Z')}")
        logger.debug(f"Last auto backup date: {last_time_est.date()}, Today: {now_est.date()}")

        if last_time_est.date() != now_est.date():
            # Haven't done auto backup today yet, so do it now
            logger.info("Starting daily auto backup...")
            await self.create_backup(log_channel=True, reason="Auto daily backup (10 AM EST)", is_auto=True)
            await self.cleanup_old_backups()
        else:
            logger.info("Already auto-backed up today, skipping")
    
    async def create_backup(self, log_channel=False, reason=None, is_auto=False):
        """Handles the actual backup logic"""
        lifetime_db = os.path.join(self.db_dir, "lifetime.db")
        annual_db = os.path.join(self.db_dir, "annual.db")
        
        logger.debug(f"Looking for databases: lifetime={lifetime_db} (exists={os.path.exists(lifetime_db)}), annual={annual_db} (exists={os.path.exists(annual_db)})")

        missing = [db for db in [lifetime_db, annual_db] if not os.path.exists(db)]
        if missing:
            error_msg = f"❌ Missing database files: {', '.join(os.path.basename(m) for m in missing)}"
            logger.error(error_msg)
            return False, error_msg
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        prefix = "auto_" if is_auto else ""
        lifetime_backup = os.path.join(self.backup_dir, f"{prefix}lifetime_{timestamp}.db")
        annual_backup = os.path.join(self.backup_dir, f"{prefix}annual_{timestamp}.db")
        
        try:
            shutil.copy2(lifetime_db, lifetime_backup)
            shutil.copy2(annual_db, annual_backup)
            
            logger.info(f"Files copied successfully: {os.path.basename(lifetime_backup)}, {os.path.basename(annual_backup)}")
            
            # Record last backup time
            with open(self.last_backup_file, "w") as f:
                f.write(datetime.now().isoformat())
            
            # Record last auto backup time if this was automatic
            if is_auto:
                with open(self.last_auto_backup_file, "w") as f:
                    f.write(datetime.now().isoformat())
            
            # File sizes
            lifetime_size = os.path.getsize(lifetime_db) / (1024 * 1024)
            annual_size = os.path.getsize(annual_db) / (1024 * 1024)
            total_size = lifetime_size + annual_size
            
            logger.info("Backup completed successfully")
            return True, f"✅ Backup complete! (`{lifetime_size:.2f}` MB lifetime, `{annual_size:.2f}` MB annual)"

        except Exception as e:
            error_msg = f"❌ Backup failed: `{e}`"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    async def cleanup_old_backups(self):
        """Delete backup files older than MAX_BACKUP_AGE (30 days)"""
        try:
            now = datetime.now()
            deleted_count = 0
            
            for filename in os.listdir(self.backup_dir):
                # Skip the last_backup.txt file
                if filename == "last_backup.txt":
                    continue
                
                filepath = os.path.join(self.backup_dir, filename)
                
                # Only process .db files
                if not filename.endswith(".db"):
                    continue
                
                # Get file modification time
                file_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                
                # Delete if older than MAX_BACKUP_AGE
                if now - file_time > MAX_BACKUP_AGE:
                    os.remove(filepath)
                    deleted_count += 1
                    logger.info(f"Deleted old backup: {filename}")

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old backup file(s)")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}", exc_info=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(BackupXP(bot))