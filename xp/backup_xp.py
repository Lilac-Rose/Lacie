import discord
from discord import app_commands
from discord.ext import commands
import os
import shutil
from datetime import datetime
from moderation.loader import ModerationBase

class BackupXP(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.backup_dir = os.path.join(self.base_dir, "backups")
        os.makedirs(self.backup_dir, exist_ok=True)

    @app_commands.command(name="backup_xp", description="Backup both lifetime and annual XP databases")
    @ModerationBase.is_admin()
    async def backup_xp(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        # Define source files
        lifetime_db = os.path.join(self.base_dir, "lifetime.db")
        annual_db = os.path.join(self.base_dir, "annual.db")

        # Make sure both databases exist
        missing = [db for db in [lifetime_db, annual_db] if not os.path.exists(db)]
        if missing:
            return await interaction.followup.send(
                f"❌ Missing database files: {', '.join(os.path.basename(m) for m in missing)}"
            )

        # Create timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # Define backup file paths
        lifetime_backup = os.path.join(self.backup_dir, f"lifetime_{timestamp}.db")
        annual_backup = os.path.join(self.backup_dir, f"annual_{timestamp}.db")

        try:
            shutil.copy2(lifetime_db, lifetime_backup)
            shutil.copy2(annual_db, annual_backup)
        except Exception as e:
            return await interaction.followup.send(f"❌ Backup failed: `{e}`")

        await interaction.followup.send(
            f"✅ Databases backed up successfully!\n"
            f"**Lifetime:** `{os.path.basename(lifetime_backup)}`\n"
            f"**Annual:** `{os.path.basename(annual_backup)}`"
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(BackupXP(bot))