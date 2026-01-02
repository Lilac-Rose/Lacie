import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiosqlite
from datetime import datetime, timedelta, timezone
import re
from pathlib import Path


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


class ReminderCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Database will be stored next to this Python file
        self.db_path = Path(__file__).parent / "reminders.db"

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
        """Called automatically when the cog is added — safe place to start background tasks."""
        await self.setup_database()
        if not self.check_reminders.is_running():
            self.check_reminders.start()

    # Create reminder command group
    reminder_group = app_commands.Group(name="reminder", description="Manage your reminders")

    @reminder_group.command(name="set", description="Set a reminder and get a DM when it's time")
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
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "INSERT INTO reminders (user_id, message, remind_at) VALUES (?, ?, ?)",
                    (interaction.user.id, message, remind_at.isoformat()),
                )
                await db.commit()

            # Format the time nicely
            unix_time = int(remind_at.timestamp())
            time_str = f"<t:{unix_time}:R>"
            await interaction.response.send_message(
                f"✅ Reminder set! I'll DM you about **'{message}'** {time_str}.",
                ephemeral=True
            )
        except Exception as e:
            print(f"Error in reminder_set: {e}")
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
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc)
        )

        for reminder_id, message, remind_at in rows:
            remind_time = datetime.fromisoformat(remind_at)
            unix_time = int(remind_time.timestamp())
            time_str = f"<t:{unix_time}:R>"
            
            # Calculate time remaining
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
                name=f"ID: {reminder_id} - {message}",
                value=f"⏰ {time_str} ({time_remaining})",
                inline=False
            )

        embed.set_footer(text="Use /reminder remove <id> to delete a reminder")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reminder_group.command(name="remove", description="Remove a specific reminder by ID")
    @app_commands.describe(reminder_id="The ID of the reminder to remove (from /reminder list)")
    async def reminder_remove(self, interaction: discord.Interaction, reminder_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            # First check if the reminder exists and belongs to the user
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
            
            message = row[0]
            
            # Delete the reminder
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
            # Check how many reminders the user has
            async with db.execute(
                "SELECT COUNT(*) FROM reminders WHERE user_id = ?",
                (interaction.user.id,),
            ) as cursor:
                count = (await cursor.fetchone())[0]
            
            if count == 0:
                return await interaction.response.send_message(
                    "You have no active reminders to clear!",
                    ephemeral=True
                )
            
            # Delete all reminders for this user
            await db.execute(
                "DELETE FROM reminders WHERE user_id = ?",
                (interaction.user.id,),
            )
            await db.commit()

        await interaction.response.send_message(
            f"✅ Cleared all {count} reminder(s)!",
            ephemeral=True
        )

    @tasks.loop(seconds=60)
    async def check_reminders(self):
        """Runs every minute, checks and delivers reminders."""
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, user_id, message FROM reminders WHERE remind_at <= ?",
                (now.isoformat(),),
            ) as cursor:
                reminders_due = await cursor.fetchall()

            for reminder_id, user_id, message in reminders_due:
                user = self.bot.get_user(user_id)
                if user:
                    try:
                        embed = discord.Embed(
                            title="⏰ Reminder!",
                            description=message,
                            color=discord.Color.blue(),
                            timestamp=datetime.now(timezone.utc)
                        )
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        pass  # user has DMs disabled or bot blocked

                await db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            await db.commit()

    @check_reminders.before_loop
    async def before_check_reminders(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(ReminderCog(bot))