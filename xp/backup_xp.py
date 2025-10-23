import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import shutil
from datetime import datetime, timedelta
from moderation.loader import ModerationBase

BACKUP_CHANNEL_ID = 946421558778417172
BACKUP_INTERVAL = timedelta(days=7)

class BackupXP(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.backup_dir = os.path.join(self.base_dir, "backups")
        self.last_backup_file = os.path.join(self.backup_dir, "last_backup.txt")
        os.makedirs(self.backup_dir, exist_ok=True)

        # Start the daily check task
        self.auto_backup_task.start()

    async def cog_load(self):
        """Check on startup if a backup is due"""
        await self.check_last_backup()

    def cog_unload(self):
        self.auto_backup_task.cancel()

    @app_commands.command(name="backup_xp", description="Backup both lifetime and annual XP databases")
    @ModerationBase.is_admin()
    async def backup_xp(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        success, message = await self.create_backup()
        await interaction.followup.send(message)

    @tasks.loop(hours=24)
    async def auto_backup_task(self):
        """Runs daily and checks if a weekly backup is due"""
        await self.check_last_backup()

    async def check_last_backup(self):
        """Check if the last backup was over 7 days ago or if no backup exists"""
        now = datetime.now()

        if not os.path.exists(self.last_backup_file):
            # No previous backup — make initial backup
            await self.create_backup(log_channel=True, reason="Startup initial backup")
            return

        with open(self.last_backup_file, "r") as f:
            try:
                last_time = datetime.fromisoformat(f.read().strip())
            except Exception:
                last_time = datetime.min

        if now - last_time >= BACKUP_INTERVAL:
            await self.create_backup(log_channel=True, reason="Auto weekly backup")

    async def create_backup(self, log_channel=False, reason=None):
        """Handles the actual backup logic"""
        lifetime_db = os.path.join(self.base_dir, "lifetime.db")
        annual_db = os.path.join(self.base_dir, "annual.db")

        missing = [db for db in [lifetime_db, annual_db] if not os.path.exists(db)]
        if missing:
            return False, f"❌ Missing database files: {', '.join(os.path.basename(m) for m in missing)}"

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        lifetime_backup = os.path.join(self.backup_dir, f"lifetime_{timestamp}.db")
        annual_backup = os.path.join(self.backup_dir, f"annual_{timestamp}.db")

        try:
            shutil.copy2(lifetime_db, lifetime_backup)
            shutil.copy2(annual_db, annual_backup)

            # Record last backup time
            with open(self.last_backup_file, "w") as f:
                f.write(datetime.now().isoformat())

            # File sizes
            lifetime_size = os.path.getsize(lifetime_db) / (1024 * 1024)
            annual_size = os.path.getsize(annual_db) / (1024 * 1024)
            total_size = lifetime_size + annual_size

            msg = (
                f"✅ Databases backed up successfully! ({reason or 'Manual backup'})\n"
                f"**Lifetime:** `{os.path.basename(lifetime_backup)}` ({lifetime_size:.2f} MB)\n"
                f"**Annual:** `{os.path.basename(annual_backup)}` ({annual_size:.2f} MB)\n"
                f"**Total size:** {total_size:.2f} MB"
            )

            if log_channel:
                channel = self.bot.get_channel(BACKUP_CHANNEL_ID)
                if channel:
                    await channel.send(msg)

            return True, msg

        except Exception as e:
            return False, f"❌ Backup failed: `{e}`"

async def setup(bot: commands.Bot):
    await bot.add_cog(BackupXP(bot))
