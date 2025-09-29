import discord
from discord.ext import commands
import os
import sqlite3
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"))

class ModerationBase(commands.Cog):
    """Base cog for moderation commands with shared DB and utilities"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = os.path.join(os.path.dirname(__file__), "moderation.db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.c = self.conn.cursor()
        self.initialize_db()

    def initialize_db(self):
        self.c.execute("""
        CREATE TABLE IF NOT EXISTS infractions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            reason TEXT,
            moderator_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL
        )
        """)
        self.conn.commit()

    def is_admin():
        async def predicate(ctx):
            if not any(role.id == ADMIN_ROLE_ID for role in ctx.author.roles):
                await ctx.send("You do not have permission.", ephemeral=True)
                return False
            return True
        return commands.check(predicate)

    async def log_infraction(self, guild_id, user_id, mod_id, type_, reason):
        self.c.execute("""
            INSERT INTO infractions (user_id, guild_id, type, reason, moderator_id, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, guild_id, type_, reason, mod_id, datetime.utcnow().isoformat()))
        self.conn.commit()

async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationBase(bot))