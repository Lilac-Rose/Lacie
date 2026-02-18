"""Shared ModerationBase cog with DB connection and is_admin() decorator."""
from discord.ext import commands
import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime
from utils.constants import LILAC_ID

load_dotenv()

# Load multiple admin role IDs from env (comma-separated)
ADMIN_ROLE_IDS = {
    int(role_id.strip())
    for role_id in os.getenv("ADMIN_ROLE_IDS", "").split(",")
    if role_id.strip().isdigit()
}

class ModerationBase(commands.Cog):
    """Base cog for moderation commands with shared DB and utilities"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent / "moderation.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.c = self.conn.cursor()
        self.initialize_db()

    def cog_unload(self):
        """Ensure database connection closes when the cog unloads."""
        self.conn.close()

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

    @staticmethod
    def is_admin():
        """Decorator that works for both prefix and slash commands."""
        async def predicate(target):
            user = getattr(target, "author", None) or getattr(target, "user", None)
            is_interaction = hasattr(target, "response")

            async def send_message(msg, ephemeral=False):
                if is_interaction:
                    try:
                        if not target.response.is_done():
                            await target.response.send_message(msg, ephemeral=ephemeral)
                        else:
                            await target.followup.send(msg, ephemeral=ephemeral)
                    except Exception:
                        pass
                else:
                    try:
                        await target.send(msg)
                    except Exception:
                        pass

            if not hasattr(user, "roles"):
                await send_message("Unable to check permissions in this context.", ephemeral=is_interaction)
                return False

            is_lilac = user.id == LILAC_ID

            has_admin_role = any(
                role.id in ADMIN_ROLE_IDS
                for role in user.roles
            )

            if not (has_admin_role or is_lilac):
                await send_message("You do not have permission to use this command.", ephemeral=is_interaction)
                from discord.app_commands import CheckFailure
                raise CheckFailure("User lacks admin permissions.")

            return True

        from discord import app_commands
        from discord.ext import commands

        def decorator(func):
            func = commands.check(predicate)(func)
            func = app_commands.check(predicate)(func)
            return func

        return decorator

    async def log_infraction(
        self,
        guild_id: int,
        user_id: int,
        mod_id: int,
        type_: str,
        reason: str | None
    ):
        """Log an infraction to the database."""
        self.c.execute("""
            INSERT INTO infractions (user_id, guild_id, type, reason, moderator_id, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, guild_id, type_, reason, mod_id, datetime.utcnow().isoformat()))
        self.conn.commit()

async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationBase(bot))
