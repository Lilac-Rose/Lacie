import sqlite3
import discord
from discord.ext import commands
from pathlib import Path

# The user ID to protect from pings
PROTECTED_USER_ID = 252130669919076352

# Users allowed to ping the protected user
ALLOWED_PINGERS = {
    505390548232699906,
    771709136051372032,
    692030310644187206,
    1153235432813895730,
}

DB_PATH = Path(__file__).parent.parent / "data" / "ping_protect.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ping_counts (
            user_id INTEGER PRIMARY KEY,
            count INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn

def record_ping(user_id: int):
    conn = get_db()
    conn.execute("""
        INSERT INTO ping_counts (user_id, count) VALUES (?, 1)
        ON CONFLICT(user_id) DO UPDATE SET count = count + 1
    """, (user_id,))
    conn.commit()
    conn.close()

class PingProtectListener(commands.Cog):
    """Responds when the protected user is pinged by someone not on the allowlist."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Check if the protected user is mentioned
        if not any(user.id == PROTECTED_USER_ID for user in message.mentions):
            return

        # Allow users on the allowlist (don't track them)
        if message.author.id in ALLOWED_PINGERS:
            return

        record_ping(message.author.id)
        await message.reply("Please don't ping faer", mention_author=False)

async def setup(bot: commands.Bot):
    await bot.add_cog(PingProtectListener(bot))
