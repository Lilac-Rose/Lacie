import asyncio
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

import discord
from discord.ext import commands

OWNER_ID = 252130669919076352
DB_PATH = Path(__file__).parent.parent / "data" / "scheduled.db"


def _db_init():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS scheduled (
            id INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            fire_at REAL NOT NULL,
            message TEXT NOT NULL
        )
    """)
    con.commit()
    return con


def _db_insert(job_id: int, channel_id: int, fire_at: float, message: str):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO scheduled (id, channel_id, fire_at, message) VALUES (?, ?, ?, ?)",
        (job_id, channel_id, fire_at, message),
    )
    con.commit()
    con.close()


def _db_delete(job_id: int):
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM scheduled WHERE id = ?", (job_id,))
    con.commit()
    con.close()


def _db_load_all() -> list[tuple]:
    con = sqlite3.connect(DB_PATH)
    rows = con.execute("SELECT id, channel_id, fire_at, message FROM scheduled").fetchall()
    con.close()
    return rows



def _parse_delay(time_str: str) -> float | None:
    """
    Parse a time string into seconds from now.
    Supports:
      - Relative: 30s, 10m, 2h, 1d (or combinations like 1h30m)
      - Absolute UTC: HH:MM  or  YYYY-MM-DDTHH:MM
    Returns seconds as float, or None if unparseable.
    """
    # Relative: e.g. 1h30m, 45m, 2d
    rel = re.fullmatch(r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', time_str.strip())
    if rel and any(rel.groups()):
        d, h, m, s = (int(x or 0) for x in rel.groups())
        total = d * 86400 + h * 3600 + m * 60 + s
        return float(total) if total > 0 else None

    # Absolute UTC HH:MM
    abs_hm = re.fullmatch(r'(\d{1,2}):(\d{2})', time_str.strip())
    if abs_hm:
        now = datetime.now(timezone.utc)
        target = now.replace(hour=int(abs_hm.group(1)), minute=int(abs_hm.group(2)), second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    # Absolute UTC YYYY-MM-DDTHH:MM
    try:
        target = datetime.fromisoformat(time_str.strip()).replace(tzinfo=timezone.utc)
        delta = (target - datetime.now(timezone.utc)).total_seconds()
        return delta if delta > 0 else None
    except ValueError:
        pass

    return None


class SendMessage(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._scheduled: dict[int, asyncio.Task] = {}  # id -> Task
        self._next_id = 1
        _db_init()

    async def cog_load(self):
        # re-schedule anything that was pending before the bot restarted
        rows = await asyncio.to_thread(_db_load_all)
        if rows:
            self._next_id = max(r[0] for r in rows) + 1
        now = datetime.now(timezone.utc).timestamp()
        for job_id, channel_id, fire_at, message in rows:
            # if fire_at already passed, just send it immediately
            delay = max(0.0, fire_at - now)
            self._schedule_task(job_id, channel_id, delay, message)

    def _schedule_task(self, job_id: int, channel_id: int, delay: float, message: str):
        async def _send():
            await asyncio.sleep(delay)
            channel = self.bot.get_channel(channel_id)
            if channel is not None:
                try:
                    await channel.send(message)
                except Exception:
                    pass
            # clean up regardless of whether the send succeeded
            self._scheduled.pop(job_id, None)
            await asyncio.to_thread(_db_delete, job_id)

        task = asyncio.create_task(_send())
        self._scheduled[job_id] = task
        return task

    @commands.command(name="sendmessage")
    async def send_message(self, ctx, server_id: int, channel_id: int, *, message: str):
        """Send a message to a specific channel in a specific server (owner only)."""
        if ctx.author.id != OWNER_ID:
            await ctx.send("You do not have permission to use this command.")
            return

        guild = self.bot.get_guild(server_id)
        if guild is None:
            await ctx.send(f"Could not find server with ID `{server_id}`.")
            return

        channel = guild.get_channel(channel_id)
        if channel is None:
            await ctx.send(f"Could not find channel with ID `{channel_id}` in that server.")
            return

        try:
            await channel.send(message)
            await ctx.send(f"✅ Message sent to <#{channel_id}> in **{guild.name}**.")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to send messages in that channel.")
        except Exception as e:
            await ctx.send(f"❌ Failed to send message: `{e}`")

    @commands.command(name="schedulemessage", aliases=["schedule"])
    async def schedule_message(self, ctx, channel_id: int, time_str: str, *, message: str):
        """
        Schedule a message to be sent in a channel at a future time (owner only).

        Time formats:
          Relative — 30s, 10m, 2h, 1d, 1h30m
          Absolute UTC — 15:30  or  2026-03-06T15:30

        Usage: !schedulemessage <channel_id> <time> <message>
        """
        if ctx.author.id != OWNER_ID:
            await ctx.send("You do not have permission to use this command.")
            return

        delay = _parse_delay(time_str)
        if delay is None:
            await ctx.send(
                "❌ Couldn't parse the time. Examples: `30m`, `2h`, `1d`, `15:30`, `2026-03-06T15:30`"
            )
            return

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            await ctx.send(f"❌ Could not find channel with ID `{channel_id}`.")
            return

        job_id = self._next_id
        self._next_id += 1

        fire_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        fire_str = fire_at.strftime('%Y-%m-%d %H:%M UTC')

        # persist before scheduling so it survives a restart
        await asyncio.to_thread(_db_insert, job_id, channel_id, fire_at.timestamp(), message)
        self._schedule_task(job_id, channel_id, delay, message)

        # format the delay into something readable for the confirmation message
        h, rem = divmod(int(delay), 3600)
        m, s   = divmod(rem, 60)
        delay_fmt = f"{h}h {m}m {s}s" if h else (f"{m}m {s}s" if m else f"{s}s")

        await ctx.send(
            f"⏰ Scheduled **#{job_id}** — fires in {delay_fmt} ({fire_str})\n"
            f"Channel: <#{channel_id}> | Preview: `{message[:80]}{'…' if len(message) > 80 else ''}`"
        )

    @commands.command(name="listscheduled", aliases=["schedules"])
    async def list_scheduled(self, ctx):
        """List all pending scheduled messages (owner only)."""
        if ctx.author.id != OWNER_ID:
            await ctx.send("You do not have permission to use this command.")
            return

        if not self._scheduled:
            await ctx.send("No scheduled messages pending.")
            return

        lines = [f"**{job_id}** — task pending" for job_id in self._scheduled]
        await ctx.send("**Scheduled messages:**\n" + "\n".join(lines))

    @commands.command(name="cancelscheduled", aliases=["cancel"])
    async def cancel_scheduled(self, ctx, job_id: int):
        """Cancel a scheduled message by its ID (owner only)."""
        if ctx.author.id != OWNER_ID:
            await ctx.send("You do not have permission to use this command.")
            return

        task = self._scheduled.pop(job_id, None)
        if task is None:
            await ctx.send(f"❌ No scheduled message with ID `{job_id}`.")
            return

        task.cancel()
        await asyncio.to_thread(_db_delete, job_id)
        await ctx.send(f"✅ Cancelled scheduled message **#{job_id}**.")


async def setup(bot):
    await bot.add_cog(SendMessage(bot))
