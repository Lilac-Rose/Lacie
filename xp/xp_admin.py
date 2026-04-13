import discord
from discord.ext import commands
from discord import app_commands
from moderation.loader import ModerationBase
from xp.add_xp import get_db
from .groups import xp_admin_group
import time

class XPAdmin(commands.Cog):
    """Admin slash commands to manage XP for users."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Register all admin commands onto the shared xpadmin group
        xp_admin_group.add_command(app_commands.command(name="set", description="Set a user's XP directly.")(self.xp_set))
        xp_admin_group.add_command(app_commands.command(name="add", description="Add XP to a user.")(self.xp_add))
        xp_admin_group.add_command(app_commands.command(name="remove", description="Remove XP from a user.")(self.xp_remove))

    def parse_lifetime_arg(self, arg: str | None) -> bool:
        """Return False if the arg is 'annual', True otherwise."""
        return False if arg and arg.lower() == "annual" else True

    @ModerationBase.is_admin()
    @app_commands.describe(
        user="The user to modify.",
        amount="The amount of XP to set.",
        db_type="'annual' for annual XP, omit for lifetime."
    )
    async def xp_set(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        amount: int,
        db_type: str | None = None,
    ):
        lifetime = self.parse_lifetime_arg(db_type)
        conn, cur = get_db(lifetime)
        cur.execute("SELECT xp FROM xp WHERE user_id = ?", (str(user.id),))
        row = cur.fetchone()
        old_xp = row[0] if row else 0

        if row:
            cur.execute("UPDATE xp SET xp = ? WHERE user_id = ?", (amount, str(user.id)))
        else:
            cur.execute(
                "INSERT INTO xp (user_id, xp, level, last_message) VALUES (?, ?, 0, ?)",
                (str(user.id), amount, int(time.time()))
            )
        conn.commit()
        conn.close()
        await interaction.response.send_message(
            f"✅ User {user.mention} XP updated ({'lifetime' if lifetime else 'annual'}): {old_xp} → {amount}",
            ephemeral=True
        )

    @ModerationBase.is_admin()
    @app_commands.describe(
        user="The user to modify.",
        amount="The amount of XP to add.",
        db_type="'annual' for annual XP, omit for lifetime."
    )
    async def xp_add(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        amount: int,
        db_type: str | None = None,
    ):
        lifetime = self.parse_lifetime_arg(db_type)
        conn, cur = get_db(lifetime)
        cur.execute("SELECT xp FROM xp WHERE user_id = ?", (str(user.id),))
        row = cur.fetchone()
        old_xp = row[0] if row else 0
        new_xp = old_xp + amount

        if row:
            cur.execute("UPDATE xp SET xp = ? WHERE user_id = ?", (new_xp, str(user.id)))
        else:
            cur.execute(
                "INSERT INTO xp (user_id, xp, level, last_message) VALUES (?, ?, 0, ?)",
                (str(user.id), new_xp, int(time.time()))
            )
        conn.commit()
        conn.close()
        await interaction.response.send_message(
            f"✅ User {user.mention} XP updated ({'lifetime' if lifetime else 'annual'}): {old_xp} → {new_xp}",
            ephemeral=True
        )

    @ModerationBase.is_admin()
    @app_commands.describe(
        user="The user to modify.",
        amount="The amount of XP to remove.",
        db_type="'annual' for annual XP, omit for lifetime."
    )
    async def xp_remove(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        amount: int,
        db_type: str | None = None,
    ):
        lifetime = self.parse_lifetime_arg(db_type)
        conn, cur = get_db(lifetime)
        cur.execute("SELECT xp FROM xp WHERE user_id = ?", (str(user.id),))
        row = cur.fetchone()
        old_xp = row[0] if row else 0
        new_xp = max(0, old_xp - amount)

        if row:
            cur.execute("UPDATE xp SET xp = ? WHERE user_id = ?", (new_xp, str(user.id)))
            conn.commit()
            await interaction.response.send_message(
                f"✅ User {user.mention} XP updated ({'lifetime' if lifetime else 'annual'}): {old_xp} → {new_xp}",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"⚠️ User {user.mention} has no {'lifetime' if lifetime else 'annual'} XP.",
                ephemeral=True
            )
        conn.close()

    async def cog_unload(self):
        xp_admin_group.remove_command("set")
        xp_admin_group.remove_command("add")
        xp_admin_group.remove_command("remove")

async def setup(bot: commands.Bot):
    await bot.add_cog(XPAdmin(bot))