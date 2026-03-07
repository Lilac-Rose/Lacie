import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiosqlite
from datetime import datetime, timedelta, timezone
import re
from pathlib import Path
from embed.embed_color import get_embed_color
from utils.logger import get_logger
from cryptography.fernet import Fernet, InvalidToken
from dateutil import parser as dateutil_parser
from dateutil import tz

logger = get_logger(__name__)

KEY_PATH = Path(__file__).parent.parent / "data" / "reminder.key"


def load_or_create_key() -> Fernet:
    if KEY_PATH.exists():
        key = KEY_PATH.read_bytes()
    else:
        key = Fernet.generate_key()
        KEY_PATH.write_bytes(key)
    return Fernet(key)


fernet = load_or_create_key()


def encrypt(text: str) -> str:
    return fernet.encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return fernet.decrypt(token.strip().encode()).decode()
    except InvalidToken:
        logger.warning("Failed to decrypt reminder message (InvalidToken) — returning raw value. This may indicate a key mismatch or a pre-encryption entry.")
        return token
    except Exception as e:
        logger.error(f"Unexpected error decrypting reminder message: {e}", exc_info=True)
        return token


def parse_timeframe(timeframe: str) -> timedelta:
    """Parse strings like '1h', '2d', '3w', '30m' into timedelta."""
    pattern = r"(\d+)\s*(s|m|h|d|w)"
    match = re.fullmatch(pattern, timeframe.strip().lower())
    if not match:
        raise ValueError("Invalid time format. Use something like '10m', '2h', '3d', or '1w'.")

    value, unit = match.groups()
    value = int(value)
    match unit:
        case "s":
            return timedelta(seconds=value)
        case "m":
            return timedelta(minutes=value)
        case "h":
            return timedelta(hours=value)
        case "d":
            return timedelta(days=value)
        case "w":
            return timedelta(weeks=value)
    raise ValueError("Invalid time unit.")


def parse_datetime(when: str, tzname: str | None) -> datetime:
    """
    Parse a human-readable date/time string into a UTC-aware datetime.
    Supports formats like 'March 5 2:30pm', '2026-03-05 14:30', '5th 3pm', etc.
    tzname: IANA timezone name or UTC offset string like 'US/Eastern', 'UTC+5', 'EST'
    """
    user_tz = tz.UTC
    if tzname:
        resolved = tz.gettz(tzname)
        if resolved is None:
            raise ValueError(f"Unknown timezone '{tzname}'. Use an IANA name like 'US/Eastern' or 'UTC+5'.")
        user_tz = resolved

    now_user = datetime.now(user_tz)

    try:
        # Use now_user as the default so missing date parts fall back to today
        parsed = dateutil_parser.parse(when, default=now_user)
    except (ValueError, OverflowError):
        raise ValueError(
            "Couldn't understand that date/time. Try something like:\n"
            "`March 5 2:30pm`, `2026-03-05 14:30`, `5th at 9am`"
        )

    # If no timezone info in the parsed string, attach the user's tz
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=user_tz)

    # If the result is in the past and the user didn't specify a year, roll to next year
    if parsed < now_user and str(now_user.year) not in when and str(now_user.year - 1) not in when:
        parsed = parsed.replace(year=parsed.year + 1)

    if parsed < datetime.now(timezone.utc):
        raise ValueError("That time is in the past.")

    return parsed.astimezone(timezone.utc)


class ReminderCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "data" / "reminders.db"

    async def setup_database(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    message TEXT,
                    remind_at TEXT
                )"""
            )
            await db.commit()

    async def cog_load(self):
        await self.setup_database()
        if not self.check_reminders.is_running():
            self.check_reminders.start()

    async def _insert_reminder(self, user_id: int, message: str, remind_at: datetime) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO reminders (user_id, message, remind_at) VALUES (?, ?, ?)",
                (user_id, encrypt(message), remind_at.isoformat()),
            )
            await db.commit()
            async with db.execute("SELECT last_insert_rowid()") as cursor:
                return (await cursor.fetchone())[0]

    reminder_group = app_commands.Group(name="reminder", description="Manage your reminders")

    @reminder_group.command(name="set", description="Set a reminder using a duration (e.g. '10m', '2h', '3d')")
    @app_commands.describe(
        timeframe="How long until reminder (e.g., '10m', '2h', '3d', '1w')",
        message="What to remind you about"
    )
    async def reminder_set(self, interaction: discord.Interaction, timeframe: str, message: str):
        try:
            try:
                delta = parse_timeframe(timeframe)
            except ValueError as e:
                return await interaction.response.send_message(str(e), ephemeral=True)

            remind_at = datetime.now(timezone.utc) + delta
            await self._insert_reminder(interaction.user.id, message, remind_at)

            unix_time = int(remind_at.timestamp())
            await interaction.response.send_message(
                f"✅ Reminder set! I'll DM you about **'{message}'** <t:{unix_time}:R>.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error in reminder_set: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    @reminder_group.command(name="at", description="Set a reminder for a specific date/time (e.g. 'March 5 2:30pm')")
    @app_commands.describe(
        when="Date and time for the reminder, e.g. 'March 5 2:30pm', '2026-03-05 14:30', '5th at 9am'",
        message="What to remind you about",
        timezone="Your timezone, e.g. 'US/Eastern', 'UTC+5', 'Europe/London' (default: UTC)"
    )
    async def reminder_at(self, interaction: discord.Interaction, when: str, message: str, timezone: str = None):
        try:
            try:
                remind_at = parse_datetime(when, timezone)
            except ValueError as e:
                return await interaction.response.send_message(str(e), ephemeral=True)

            await self._insert_reminder(interaction.user.id, message, remind_at)

            unix_time = int(remind_at.timestamp())
            await interaction.response.send_message(
                f"✅ Reminder set! I'll DM you about **'{message}'** on <t:{unix_time}:F> (<t:{unix_time}:R>).",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error in reminder_at: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    @reminder_group.command(name="list", description="View your active reminders")
    async def reminder_list(self, interaction: discord.Interaction):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, message, remind_at FROM reminders WHERE user_id = ? ORDER BY remind_at",
                (interaction.user.id,),
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return await interaction.response.send_message(
                "You have no active reminders!", ephemeral=True
            )

        embed = discord.Embed(
            title="📝 Your Reminders",
            color=get_embed_color(interaction.user.id),
            timestamp=datetime.now(timezone.utc)
        )

        for reminder_id, message, remind_at in rows:
            message = decrypt(message)
            remind_time = datetime.fromisoformat(remind_at)
            unix_time = int(remind_time.timestamp())

            now = datetime.now(timezone.utc)
            time_diff = remind_time - now

            if time_diff.total_seconds() > 0:
                days = time_diff.days
                hours, remainder = divmod(time_diff.seconds, 3600)
                minutes, _ = divmod(remainder, 60)

                if days > 0:
                    time_remaining = f"in {days}d {hours}h"
                elif hours > 0:
                    time_remaining = f"in {hours}h {minutes}m"
                else:
                    time_remaining = f"in {minutes}m"
            else:
                time_remaining = "overdue"

            embed.add_field(
                name=f"ID: {reminder_id} — {message}",
                value=f"⏰ <t:{unix_time}:F> ({time_remaining})",
                inline=False
            )

        embed.set_footer(text="Use /reminder remove <id> to delete a reminder")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reminder_group.command(name="remove", description="Remove a specific reminder by ID")
    @app_commands.describe(reminder_id="The ID of the reminder to remove (from /reminder list)")
    async def reminder_remove(self, interaction: discord.Interaction, reminder_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT message FROM reminders WHERE id = ? AND user_id = ?",
                (reminder_id, interaction.user.id),
            ) as cursor:
                row = await cursor.fetchone()

            if not row:
                return await interaction.response.send_message(
                    f"❌ Reminder with ID {reminder_id} not found or doesn't belong to you.",
                    ephemeral=True
                )

            message = decrypt(row[0])

            await db.execute(
                "DELETE FROM reminders WHERE id = ? AND user_id = ?",
                (reminder_id, interaction.user.id),
            )
            await db.commit()

        await interaction.response.send_message(
            f"✅ Removed reminder: **'{message}'**",
            ephemeral=True
        )

    @reminder_group.command(name="clear", description="Remove all your active reminders")
    async def reminder_clear(self, interaction: discord.Interaction):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM reminders WHERE user_id = ?",
                (interaction.user.id,),
            ) as cursor:
                count = (await cursor.fetchone())[0]

            if count == 0:
                return await interaction.response.send_message(
                    "You have no active reminders to clear!", ephemeral=True
                )

            await db.execute("DELETE FROM reminders WHERE user_id = ?", (interaction.user.id,))
            await db.commit()

        await interaction.response.send_message(
            f"✅ Cleared all {count} reminder(s)!", ephemeral=True
        )

    @tasks.loop(seconds=60)
    async def check_reminders(self):
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, user_id, message FROM reminders WHERE remind_at <= ?",
                (now.isoformat(),),
            ) as cursor:
                reminders_due = await cursor.fetchall()

            if reminders_due:
                ids = [r[0] for r in reminders_due]
                await db.execute(
                    f"DELETE FROM reminders WHERE id IN ({','.join('?' * len(ids))})",
                    ids,
                )
                await db.commit()

        for reminder_id, user_id, message in reminders_due:
            decrypted = decrypt(message)
            user = self.bot.get_user(user_id)
            if user:
                try:
                    embed = discord.Embed(
                        title="⏰ Reminder!",
                        description=decrypted,
                        color=get_embed_color(user_id),
                        timestamp=datetime.now(timezone.utc)
                    )
                    await user.send(embed=embed)
                except (discord.Forbidden, discord.HTTPException):
                    pass

    @check_reminders.before_loop
    async def before_check_reminders(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(ReminderCog(bot))
