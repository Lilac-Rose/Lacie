import discord
import sqlite3
from discord.ext import commands
from discord import app_commands

DB_PATH = "embed_colors.db"

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

    def get_user_color(self, user:discord.User) -> discord.Color:
        db = self.get_db()
        cursor = db.cursor()
        cursor.execute("SELECT color FROM user_embed_colors WHERE user_id = ?", (user.id,))
        result = cursor.fetchone()
        db.close()
        if result and result[0]:
            return discord.Color(int(result[0], 16))
        return user.accent_color or discord.Color.blurple()

    @app_commands.command(name="setcolor", description="Set your preferred embed color (hex, e.g. #ff66cc).")
    async def setcolor(self, interaction: discord.Interaction, hex_color: str):
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

        await interaction.response.send_message(f"Your embed color has been set to `{hex_color}`")

    @app_commands.command(name="mycolor", description="View your current embed color.")
    async def mycolor(self, interaction: discord.Interaction):
        color = self.get_user_color(interaction.user)
        hex_code = f"#{color.value:06x}"
        embed = discord.Embed(
            title="Your Embed Color",
            description=f"Current color: `{hex_code}`",
            color=color
        )
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(EmbedColor(bot))