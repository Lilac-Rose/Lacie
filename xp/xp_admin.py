import discord
from discord.ext import commands
from moderation.loader import ModerationBase
from xp.add_xp import get_db
import time

class XPAdmin(commands.Cog):
    """Admin commands to manage XP for users."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.group(name="xp", invoke_without_command=True)
    @ModerationBase.is_admin()
    async def xp(self, ctx):
        await ctx.send("Usage: `!xp set/add/remove <user_id> <amount> [annual]`")

    def parse_lifetime_arg(self, arg: str | None) -> bool:
        """Return False if the arg is 'annual', True otherwise."""
        return False if arg and arg.lower() == "annual" else True

    @xp.command(name="set")
    @ModerationBase.is_admin()
    async def xp_set(self, ctx, user_id: int, amount: int, db_type: str = None):
        lifetime = self.parse_lifetime_arg(db_type)
        conn, cur = get_db(lifetime)
        cur.execute("SELECT xp FROM xp WHERE user_id = ?", (str(user_id),))
        row = cur.fetchone()
        old_xp = row[0] if row else 0

        if row:
            cur.execute("UPDATE xp SET xp = ? WHERE user_id = ?", (amount, str(user_id)))
        else:
            cur.execute(
                "INSERT INTO xp (user_id, xp, level, last_message) VALUES (?, ?, 0, ?)",
                (str(user_id), amount, int(time.time()))
            )
        conn.commit()
        conn.close()
        await ctx.send(
            f"User <@{user_id}> XP updated ({'lifetime' if lifetime else 'annual'}): {old_xp} → {amount}"
        )

    @xp.command(name="add")
    @ModerationBase.is_admin()
    async def xp_add(self, ctx, user_id: int, amount: int, db_type: str = None):
        lifetime = self.parse_lifetime_arg(db_type)
        conn, cur = get_db(lifetime)
        cur.execute("SELECT xp FROM xp WHERE user_id = ?", (str(user_id),))
        row = cur.fetchone()
        old_xp = row[0] if row else 0
        new_xp = old_xp + amount

        if row:
            cur.execute("UPDATE xp SET xp = ? WHERE user_id = ?", (new_xp, str(user_id)))
        else:
            cur.execute(
                "INSERT INTO xp (user_id, xp, level, last_message) VALUES (?, ?, 0, ?)",
                (str(user_id), new_xp, int(time.time()))
            )
        conn.commit()
        conn.close()
        await ctx.send(
            f"User <@{user_id}> XP updated ({'lifetime' if lifetime else 'annual'}): {old_xp} → {new_xp}"
        )

    @xp.command(name="remove")
    @ModerationBase.is_admin()
    async def xp_remove(self, ctx, user_id: int, amount: int, db_type: str = None):
        lifetime = self.parse_lifetime_arg(db_type)
        conn, cur = get_db(lifetime)
        cur.execute("SELECT xp FROM xp WHERE user_id = ?", (str(user_id),))
        row = cur.fetchone()
        old_xp = row[0] if row else 0
        new_xp = max(0, old_xp - amount)

        if row:
            cur.execute("UPDATE xp SET xp = ? WHERE user_id = ?", (new_xp, str(user_id)))
            conn.commit()
            await ctx.send(
                f"User <@{user_id}> XP updated ({'lifetime' if lifetime else 'annual'}): {old_xp} → {new_xp}"
            )
        else:
            await ctx.send(f"User <@{user_id}> has no {'lifetime' if lifetime else 'annual'} XP.")
        conn.close()


async def setup(bot: commands.Bot):
    await bot.add_cog(XPAdmin(bot))
