import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import os
from moderation.loader import ModerationBase
from xp.add_xp import get_db

class ResetXPView(discord.ui.View):
    def __init__(self, author: discord.User, db_label: str, on_confirm):
        super().__init__(timeout=30)
        self.author = author
        self.db_label = db_label
        self.on_confirm = on_confirm

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("You can't respond to this confirmation.", ephemeral=False)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            f"⚠️ Please confirm **again** to reset the {self.db_label} XP leaderboard.",
            ephemeral=False,
            view=FinalResetXPView(self.author, self.db_label, self.on_confirm)
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Reset cancelled.", ephemeral=False)
        self.stop()


class FinalResetXPView(discord.ui.View):
    def __init__(self, author: discord.User, db_label: str, on_confirm):
        super().__init__(timeout=30)
        self.author = author
        self.db_label = db_label
        self.on_confirm = on_confirm

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("You can't respond to this confirmation.", ephemeral=False)
            return False
        return True

    @discord.ui.button(label="Final Confirm", style=discord.ButtonStyle.danger)
    async def final_confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_confirm(interaction)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Reset cancelled.", ephemeral=False)
        self.stop()


class ResetAnnual(commands.Cog):
    """Admin slash command to reset XP databases."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="resetxp", description="Reset either the annual or lifetime XP leaderboard.")
    @app_commands.describe(db_type="Choose which database to reset: 'annual' or 'lifetime'.")
    @ModerationBase.is_admin()
    async def reset_xp(self, interaction: discord.Interaction, db_type: str):
        db_type = db_type.lower()
        if db_type not in ["annual", "lifetime"]:
            await interaction.response.send_message("❌ Invalid option. Use 'annual' or 'lifetime'.", ephemeral=False)
            return

        db_label = "annual" if db_type == "annual" else "lifetime"

        async def do_reset(inter: discord.Interaction):
            lifetime = False if db_type == "annual" else True
            conn, cur = get_db(lifetime)
            cur.execute("DELETE FROM xp")
            conn.commit()
            conn.close()
            await inter.response.send_message(f"✅ {db_label.capitalize()} XP leaderboard has been reset.", ephemeral=False)

        view = ResetXPView(interaction.user, db_label, do_reset)
        await interaction.response.send_message(
            f"⚠️ Are you **sure** you want to reset the {db_label} XP leaderboard? This action cannot be undone.",
            ephemeral=False,
            view=view
        )


async def setup(bot):
    await bot.add_cog(ResetAnnual(bot))
