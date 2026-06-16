from discord.ext import commands
import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime
from utils.constants import LILAC_ID

load_dotenv()

# Load admin role IDs from env (comma-separated list of integer IDs)
ADMIN_ROLE_IDS = {
    int(role_id.strip())
    for role_id in os.getenv("ADMIN_ROLE_IDS", "").split(",")
    if role_id.strip().isdigit()
}


class ModerationBase(commands.Cog):
    """Base cog for all moderation commands.

    Provides a shared SQLite connection, the infractions table schema,
    the is_admin() permission check decorator, and log_infraction().
    All moderation cogs inherit from this class.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "data" / "moderation.db"
        # One shared connection per cog instance — closed in cog_unload
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.c = self.conn.cursor()
        self.initialize_db()

    async def cog_unload(self):
        """Close the database connection when the cog unloads."""
        self.conn.close()

    def initialize_db(self):
        """Create the infractions table if it does not already exist."""
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
        """Permission check decorator that works for both prefix and slash commands.

        Checks whether the invoking user has an admin role (from ADMIN_ROLE_IDS)
        or is the bot owner (LILAC_ID). Sends an error message and raises
        CheckFailure if the check fails.
        """
        async def predicate(target):
            # target is either a Context (prefix command) or Interaction (slash command)
            user = getattr(target, "author", None) or getattr(target, "user", None)
            is_interaction = hasattr(target, "response")

            # Unified send helper so we don't have to branch on interaction type everywhere
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

            is_lilac = user.id == LILAC_ID  # owner always passes

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

        # Apply both checks so the decorator works regardless of command type
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
        """Insert an infraction record into the database.

        Parameters
        ----------
        guild_id:
            The guild the infraction occurred in.
        user_id:
            The user who received the infraction.
        mod_id:
            The moderator who issued the infraction.
        type_:
            The infraction type (e.g. 'ban', 'warn', 'kick').
        reason:
            Optional reason text.
        """
        self.c.execute("""
            INSERT INTO infractions (user_id, guild_id, type, reason, moderator_id, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, guild_id, type_, reason, mod_id, datetime.utcnow().isoformat()))
        self.conn.commit()


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationBase(bot))
