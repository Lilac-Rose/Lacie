"""Embed color preference system allowing users to set custom embed colors."""
import discord
import sqlite3
from pathlib import Path
from discord.ext import commands
from discord import app_commands

DB_PATH = Path(__file__).parent.parent / "data" / "embed_colors.db"


def get_embed_color(user_id: int) -> discord.Color:
    db = sqlite3.connect(DB_PATH)
    cursor = db.cursor()
    cursor.execute("SELECT color FROM user_embed_colors WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    db.close()
    if result and result[0]:
        return discord.Color(int(result[0], 16))
    return discord.Color.blurple()


class EmbedColor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_table()
    
    def get_db(self):
        return sqlite3.connect(DB_PATH)
    
    def setup_table(self):
        db = self.get_db()
        cursor = db.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_embed_colors (
                user_id INTEGER PRIMARY KEY,
                color TEXT
            )
        """)
        db.commit()
        db.close()
    
    def get_user_color(self, user: discord.User) -> discord.Color:
        db = self.get_db()
        cursor = db.cursor()
        cursor.execute("SELECT color FROM user_embed_colors WHERE user_id = ?", (user.id,))
        result = cursor.fetchone()
        db.close()
        if result and result[0]:
            return discord.Color(int(result[0], 16))
        return user.accent_color or discord.Color.blurple()
    
    # Create a command group
    embed_group = app_commands.Group(name="embedcolor", description="Manage your embed color preferences")
    
    @embed_group.command(name="set", description="Set your preferred embed color (hex, e.g. #ff66cc)")
    @app_commands.describe(hex_color="Hex color code (e.g., #ff66cc)")
    async def set_color(self, interaction: discord.Interaction, hex_color: str):
        if not hex_color.startswith("#") or len(hex_color) != 7:
            await interaction.response.send_message("Please provide a valid hex color in the format: `#rrggbb`.", ephemeral=True)
            return
        
        try:
            int(hex_color[1:], 16)
        except ValueError:
            await interaction.response.send_message("Invalid hex format. Example: `#7289da`", ephemeral=True)
            return
        
        db = self.get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO user_embed_colors (user_id, color)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET color=excluded.color
        """, (interaction.user.id, hex_color[1:]))
        db.commit()
        db.close()
        
        embed = discord.Embed(
            title="✅ Embed Color Updated",
            description=f"Your embed color has been set to `{hex_color}`.\nHere's how it looks!",
            color=discord.Color(int(hex_color[1:], 16))
        )
    
        await interaction.response.send_message(embed=embed)
        
    @embed_group.command(name="view", description="View your current embed color")
    async def view_color(self, interaction: discord.Interaction):
        color = self.get_user_color(interaction.user)
        hex_code = f"#{color.value:06x}"
        embed = discord.Embed(
            title="Your Embed Color",
            description=f"Current color: `{hex_code}`",
            color=color
        )
        await interaction.response.send_message(embed=embed)
    
    @embed_group.command(name="remove", description="Remove your custom embed color")
    async def remove_color(self, interaction: discord.Interaction):
        db = self.get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM user_embed_colors WHERE user_id = ?", (interaction.user.id,))
        changes = db.total_changes
        db.commit()
        db.close()
        
        if changes > 0:
            await interaction.response.send_message("Your custom embed color has been removed. Default colors will be used.", ephemeral=True)
        else:
            await interaction.response.send_message("You don't have a custom embed color set.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(EmbedColor(bot))