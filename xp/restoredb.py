import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button
import os
import shutil
from moderation.loader import ModerationBase

class RestoreXP(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.backup_dir = os.path.join(self.base_dir, "backups")

    @app_commands.command(name="restorebackup", description="Restore a lifetime or annual XP database from backup")
    @app_commands.describe(
        db_type="Choose which database to restore",
        filename="Select the backup file to restore"
    )
    @ModerationBase.is_admin()
    async def restorebackup(self, interaction: discord.Interaction, db_type: str, filename: str):
        await interaction.response.defer(ephemeral=False)

        # Validate db_type
        if db_type not in ["lifetime", "annual"]:
            return await interaction.followup.send("❌ Invalid database type. Choose either `lifetime` or `annual`.")

        db_path = os.path.join(self.base_dir, f"{db_type}.db")
        backup_path = os.path.join(self.backup_dir, filename)

        # Check if the backup file exists
        if not os.path.exists(backup_path):
            return await interaction.followup.send(f"❌ Backup file `{filename}` not found in backups folder.")

        view = View(timeout=30)
        confirmed = {"value": False}

        async def yes_callback(btn_inter: discord.Interaction):
            if btn_inter.user != interaction.user:
                await btn_inter.response.send_message("You can’t confirm this action.", ephemeral=True)
                return
            confirmed["value"] = True
            await btn_inter.response.edit_message(content=f"✅ Confirmed restore of `{filename}` to `{db_type}.db`.", view=None)
            view.stop()

        async def no_callback(btn_inter: discord.Interaction):
            if btn_inter.user != interaction.user:
                await btn_inter.response.send_message("You can’t cancel this action.", ephemeral=True)
                return
            confirmed["value"] = False
            await btn_inter.response.edit_message(content="❌ Restore cancelled.", view=None)
            view.stop()

        yes_button = Button(label="Yes", style=discord.ButtonStyle.green)
        no_button = Button(label="No", style=discord.ButtonStyle.red)
        yes_button.callback = yes_callback
        no_button.callback = no_callback
        view.add_item(yes_button)
        view.add_item(no_button)

        await interaction.followup.send(
            f"⚠️ Are you sure you want to **restore** `{db_type}.db` from `{filename}`?\n"
            f"This will **overwrite the current database** and cannot be undone.",
            view=view
        )

        await view.wait()
        if not confirmed["value"]:
            return  # Cancelled or timed out

        # --- Perform Restore ---
        try:
            shutil.copy2(backup_path, db_path)
        except Exception as e:
            return await interaction.followup.send(f"❌ Restore failed: `{e}`")

        await interaction.followup.send(f"✅ `{db_type}.db` successfully restored from `{filename}`")

    @restorebackup.autocomplete("db_type")
    async def db_type_autocomplete(self, interaction: discord.Interaction, current: str):
        options = ["lifetime", "annual"]
        return [
            app_commands.Choice(name=opt, value=opt)
            for opt in options if current.lower() in opt.lower()
        ]

    @restorebackup.autocomplete("filename")
    async def filename_autocomplete(self, interaction: discord.Interaction, current: str):
        db_type = getattr(interaction.namespace, "db_type", None)
        if not db_type:
            return [app_commands.Choice(name="Select db_type first", value="")]

        files = [
            f for f in os.listdir(self.backup_dir)
            if f.startswith(db_type) and f.endswith(".db")
        ]
        files.sort(reverse=True)  # Newest first

        return [
            app_commands.Choice(name=f, value=f)
            for f in files if current.lower() in f.lower()
        ][:25]  # Discord's limit

async def setup(bot: commands.Bot):
    await bot.add_cog(RestoreXP(bot))
