"""
admin_events.py — Owner-only admin commands for the 5th Anniversary event.

All commands are gated behind two layers:
  1. default_member_permissions=administrator  — hides commands from non-admins in the Discord UI
  2. LILAC_ID check at the top of every body  — rejects anyone who isn't the bot owner

Cross-cog access to TimeCapsule and PuzzleHunt is done via self.bot.cogs.
"""

import json
import sqlite3
import discord
import aiohttp
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

from utils.constants import GUILD_ID, LILAC_ID
from utils.logger import get_logger

logger = get_logger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "capsule_puzzle_config.json"
CAPSULE_DB = Path(__file__).parent.parent / "data" / "capsule.db"
PUZZLE_DB  = Path(__file__).parent.parent / "data" / "puzzle.db"

EVENT_COLOR = 0xB48EAD
SITE_URL = "http://localhost:3100"


def _load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _set_capsule_state(key: str, value: str):
    conn = sqlite3.connect(CAPSULE_DB)
    c = conn.cursor()
    c.execute(
        "INSERT INTO capsule_event_state (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def _check_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id == LILAC_ID


# ---------------------------------------------------------------------------
# Admin cog
# ---------------------------------------------------------------------------

class AdminEvents(commands.Cog):
    """Owner-only admin commands for capsule, puzzle, and system management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _capsule_cog(self):
        return self.bot.cogs.get("TimeCapsule")

    def _puzzle_cog(self):
        return self.bot.cogs.get("PuzzleHunt")

    # ------------------------------------------------------------------ #
    # Command groups                                                       #
    # ------------------------------------------------------------------ #

    admin_group = app_commands.Group(
        name="admin",
        description="5th Anniversary event admin commands",
        default_member_permissions=discord.Permissions(administrator=True),
    )
    capsule_group = app_commands.Group(
        name="capsule",
        description="Time Capsule admin commands",
        parent=admin_group,
    )
    puzzle_group = app_commands.Group(
        name="puzzle",
        description="Puzzle Hunt admin commands",
        parent=admin_group,
    )
    system_group = app_commands.Group(
        name="system",
        description="System health and schedule commands",
        parent=admin_group,
    )

    # ================================================================== #
    # /admin capsule                                                       #
    # ================================================================== #

    @capsule_group.command(name="stats", description="Submission counts per day and unique user total")
    async def capsule_stats(self, interaction: discord.Interaction):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        conn = sqlite3.connect(CAPSULE_DB)
        c = conn.cursor()
        c.execute("SELECT COUNT(DISTINCT user_id) FROM capsule_submissions")
        unique_users = c.fetchone()[0]
        c.execute(
            "SELECT day, COUNT(*) FROM capsule_submissions GROUP BY day ORDER BY day"
        )
        day_counts = c.fetchall()
        conn.close()

        lines = [f"**{unique_users}** unique users have submitted at least one entry.\n"]
        cfg = _load_config()
        for day, count in day_counts:
            prompt = cfg["capsule_prompts"][day - 1]
            label = f"Day {day}" if prompt is None else f"Day {day}"
            lines.append(f"`{label}` — {count} submissions")

        embed = discord.Embed(
            title="Capsule Stats",
            description="\n".join(lines),
            color=EVENT_COLOR,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @capsule_group.command(name="view", description="View a user's full capsule contents")
    @app_commands.describe(user="The user whose capsule to view")
    async def capsule_view(self, interaction: discord.Interaction, user: discord.Member):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        conn = sqlite3.connect(CAPSULE_DB)
        c = conn.cursor()
        c.execute(
            "SELECT day, response_text, image_url, is_public, submitted_at"
            " FROM capsule_submissions WHERE user_id=? ORDER BY day",
            (user.id,),
        )
        rows = c.fetchall()
        conn.close()

        if not rows:
            await interaction.followup.send(
                f"{user.display_name} has no capsule submissions.", ephemeral=True
            )
            return

        cfg = _load_config()
        embed = discord.Embed(
            title=f"Capsule: {user.display_name}",
            color=EVENT_COLOR,
        )
        for day, text, image_url, is_public, submitted_at in rows:
            prompt = cfg["capsule_prompts"][day - 1]
            if prompt is None:
                prompt = "Wildcard"
            header = f"Day {day} {'[public]' if is_public else '[private]'}"
            value = text[:1020]
            if image_url:
                value += f"\n[image]({image_url})"
            embed.add_field(name=header, value=value, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @capsule_group.command(name="reset", description="Delete a user's capsule submission(s)")
    @app_commands.describe(user="The user", day="Specific day to delete (omit to delete all)")
    async def capsule_reset(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        day: int = None,
    ):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        conn = sqlite3.connect(CAPSULE_DB)
        c = conn.cursor()
        if day is not None:
            c.execute(
                "DELETE FROM capsule_submissions WHERE user_id=? AND day=?",
                (user.id, day),
            )
            msg = f"Deleted Day {day} submission for {user.display_name}."
        else:
            c.execute(
                "DELETE FROM capsule_submissions WHERE user_id=?", (user.id,)
            )
            msg = f"Deleted all capsule submissions for {user.display_name}."
        conn.commit()
        conn.close()
        await interaction.followup.send(msg, ephemeral=True)

    @capsule_group.command(name="force-post", description="Manually trigger a day's prompt post now")
    @app_commands.describe(day="Day number (1-7)")
    async def capsule_force_post(self, interaction: discord.Interaction, day: int):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return
        if not 1 <= day <= 7:
            await interaction.response.send_message("Day must be 1-7.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        cog = self._capsule_cog()
        if cog is None:
            await interaction.followup.send("TimeCapsule cog not loaded.", ephemeral=True)
            return

        try:
            await cog._post_daily_capsule(day)
            await interaction.followup.send(f"Day {day} capsule prompt posted.", ephemeral=True)
        except Exception as e:
            logger.exception(f"admin capsule force-post day={day}: {e}")
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @capsule_group.command(name="set-prompt", description="Override a day's prompt text without redeploying")
    @app_commands.describe(day="Day number (1-7)", text="New prompt text")
    async def capsule_set_prompt(
        self, interaction: discord.Interaction, day: int, text: str
    ):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return
        if not 1 <= day <= 7:
            await interaction.response.send_message("Day must be 1-7.", ephemeral=True)
            return
        _set_capsule_state(f"capsule_prompt_override_{day}", text)
        await interaction.response.send_message(
            f"Day {day} prompt overridden. Takes effect on next post/submit.",
            ephemeral=True,
        )

    @capsule_group.command(
        name="force-reveal",
        description="Trigger the capsule reveal early for one user or globally",
    )
    @app_commands.describe(
        user="User to reveal to (omit to run globally)",
        confirm="Must be True to run globally",
    )
    async def capsule_force_reveal(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
        confirm: bool = False,
    ):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return

        if user is None and not confirm:
            await interaction.response.send_message(
                "This will DM every capsule participant early. "
                "Pass `confirm:True` to proceed globally.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        cog = self._capsule_cog()
        if cog is None:
            await interaction.followup.send("TimeCapsule cog not loaded.", ephemeral=True)
            return

        try:
            if user is not None:
                await cog._reveal_for_user(user.id)
                await interaction.followup.send(
                    f"Reveal sent to {user.display_name}.", ephemeral=True
                )
            else:
                await cog.reveal_capsule()
                await interaction.followup.send("Global reveal triggered.", ephemeral=True)
        except Exception as e:
            logger.exception(f"admin capsule force-reveal: {e}")
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    # ================================================================== #
    # /admin puzzle                                                        #
    # ================================================================== #

    @puzzle_group.command(name="stats", description="Solve counts and first solver per day")
    @app_commands.describe(day="Specific day (omit for all days)")
    async def puzzle_stats(self, interaction: discord.Interaction, day: int = None):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        conn = sqlite3.connect(PUZZLE_DB)
        c = conn.cursor()

        days_to_show = [day] if day else list(range(1, 8))
        lines = []
        for d in days_to_show:
            c.execute("SELECT COUNT(*) FROM puzzle_solves WHERE day=?", (d,))
            total = c.fetchone()[0]
            c.execute(
                "SELECT user_id FROM puzzle_solves WHERE day=? ORDER BY solved_at ASC LIMIT 1",
                (d,),
            )
            first_row = c.fetchone()
            first = f"<@{first_row[0]}>" if first_row else "none"
            lines.append(f"**Day {d}** — {total} solves — first: {first}")
        conn.close()

        embed = discord.Embed(
            title="Puzzle Stats",
            description="\n".join(lines),
            color=EVENT_COLOR,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @puzzle_group.command(
        name="set-fragment",
        description="Override or add an accepted fragment for a day (without redeploy)",
    )
    @app_commands.describe(day="Day number (1-7)", text="New accepted fragment text")
    async def puzzle_set_fragment(
        self, interaction: discord.Interaction, day: int, text: str
    ):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return
        if not 1 <= day <= 7:
            await interaction.response.send_message("Day must be 1-7.", ephemeral=True)
            return
        _set_capsule_state(f"puzzle_fragment_override_{day}", text.strip().lower())
        await interaction.response.send_message(
            f"Day {day} fragment override set to `{text.strip().lower()}`.",
            ephemeral=True,
        )

    @puzzle_group.command(name="force-post", description="Manually trigger a day's lead-in message now")
    @app_commands.describe(day="Day number (1-7)")
    async def puzzle_force_post(self, interaction: discord.Interaction, day: int):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return
        if not 1 <= day <= 7:
            await interaction.response.send_message("Day must be 1-7.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        cog = self._puzzle_cog()
        if cog is None:
            await interaction.followup.send("PuzzleHunt cog not loaded.", ephemeral=True)
            return

        try:
            await cog._post_daily_puzzle(day)
            await interaction.followup.send(
                f"Day {day} lead-in posted.", ephemeral=True
            )
        except Exception as e:
            logger.exception(f"admin puzzle force-post day={day}: {e}")
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @puzzle_group.command(name="clear-solve", description="Remove an erroneous solve record")
    @app_commands.describe(user="The user", day="The day to clear")
    async def puzzle_clear_solve(
        self, interaction: discord.Interaction, user: discord.Member, day: int
    ):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        conn = sqlite3.connect(PUZZLE_DB)
        c = conn.cursor()
        c.execute(
            "DELETE FROM puzzle_solves WHERE user_id=? AND day=?", (user.id, day)
        )
        conn.commit()
        conn.close()
        await interaction.followup.send(
            f"Cleared Day {day} solve for {user.display_name}.", ephemeral=True
        )

    @puzzle_group.command(
        name="grant-role",
        description="Manually assign a day's solver role (for webhook failures)",
    )
    @app_commands.describe(user="The user", day="The day's solver role (0 = Puzzle Hunter)")
    async def puzzle_grant_role(
        self, interaction: discord.Interaction, user: discord.Member, day: int
    ):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        conn = sqlite3.connect(PUZZLE_DB)
        c = conn.cursor()
        c.execute("SELECT role_id FROM puzzle_roles WHERE day=?", (day,))
        row = c.fetchone()
        conn.close()

        if not row:
            await interaction.followup.send(
                f"No role ID found for day={day}. Run the bot once to create roles.",
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(row[0])
        if role is None:
            await interaction.followup.send(
                f"Role ID {row[0]} not found in this guild.", ephemeral=True
            )
            return

        try:
            await user.add_roles(role, reason="Admin manual grant — 5th Anniversary Event")
            await interaction.followup.send(
                f"Granted **{role.name}** to {user.display_name}.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "Missing permissions to assign that role.", ephemeral=True
            )

    @puzzle_group.command(name="reset-day", description="Clear all solve records for a day")
    @app_commands.describe(day="Day number (1-7)")
    async def puzzle_reset_day(self, interaction: discord.Interaction, day: int):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return
        if not 1 <= day <= 7:
            await interaction.response.send_message("Day must be 1-7.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        conn = sqlite3.connect(PUZZLE_DB)
        c = conn.cursor()
        c.execute("DELETE FROM puzzle_solves WHERE day=?", (day,))
        deleted = conn.total_changes
        conn.commit()
        conn.close()
        await interaction.followup.send(
            f"Cleared {deleted} solve record(s) for Day {day}.", ephemeral=True
        )

    @puzzle_group.command(name="reset-attempts", description="Clear a user's attempt count for a day")
    @app_commands.describe(user="The user", day="Day number (1-7)")
    async def puzzle_reset_attempts(
        self, interaction: discord.Interaction, user: discord.Member, day: int
    ):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        conn = sqlite3.connect(PUZZLE_DB)
        c = conn.cursor()
        c.execute(
            "DELETE FROM puzzle_attempts WHERE user_id=? AND day=?", (user.id, day)
        )
        deleted = conn.total_changes
        conn.commit()
        conn.close()
        await interaction.followup.send(
            f"Cleared {deleted} attempt record(s) for {user.display_name} on Day {day}.",
            ephemeral=True,
        )

    @puzzle_group.command(
        name="unlink-check",
        description="Check a user's Discord OAuth solve history (proxy for site auth status)",
    )
    @app_commands.describe(user="The user to check")
    async def puzzle_unlink_check(
        self, interaction: discord.Interaction, user: discord.Member
    ):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        conn = sqlite3.connect(PUZZLE_DB)
        c = conn.cursor()
        c.execute(
            "SELECT day, solved_at FROM puzzle_solves WHERE user_id=? ORDER BY solved_at",
            (user.id,),
        )
        solves = c.fetchall()
        c.execute(
            "SELECT day, COUNT(*) FROM puzzle_attempts WHERE user_id=? GROUP BY day ORDER BY day",
            (user.id,),
        )
        attempts = c.fetchall()
        conn.close()

        lines = [f"**{user.display_name}** (`{user.id}`)"]
        if solves:
            lines.append(f"\nSolves ({len(solves)}):")
            for day, solved_at in solves:
                lines.append(f"  Day {day} — {solved_at[:19]} UTC")
        else:
            lines.append("\nNo solves recorded. If they submitted on the site, OAuth may have failed.")

        if attempts:
            lines.append(f"\nAttempts by day:")
            for day, count in attempts:
                lines.append(f"  Day {day} — {count} attempt(s)")

        embed = discord.Embed(
            title="OAuth / Solve History",
            description="\n".join(lines),
            color=EVENT_COLOR,
        )
        embed.set_footer(
            text="Sessions are Redis-based/ephemeral — solve records are the reliable auth proxy."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ================================================================== #
    # /admin system                                                        #
    # ================================================================== #

    @system_group.command(name="health", description="Bot uptime, DB status, task loops, and site connectivity")
    async def system_health(self, interaction: discord.Interaction):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        lines = []

        # DB connectivity
        for label, path in [("capsule.db", CAPSULE_DB), ("puzzle.db", PUZZLE_DB)]:
            try:
                conn = sqlite3.connect(path)
                conn.execute("SELECT 1")
                conn.close()
                lines.append(f"`{label}` — OK")
            except Exception as e:
                lines.append(f"`{label}` — ERROR: {e}")

        # Task loop status
        capsule_cog = self._capsule_cog()
        puzzle_cog = self._puzzle_cog()

        capsule_running = (
            capsule_cog.daily_capsule_post.is_running() if capsule_cog else False
        )
        reveal_running = (
            capsule_cog.reveal_capsule.is_running() if capsule_cog else False
        )
        puzzle_running = (
            puzzle_cog.daily_puzzle_post.is_running() if puzzle_cog else False
        )

        lines.append(f"`daily_capsule_post` loop — {'running' if capsule_running else 'STOPPED'}")
        lines.append(f"`reveal_capsule` loop — {'running' if reveal_running else 'STOPPED'}")
        lines.append(f"`daily_puzzle_post` loop — {'running' if puzzle_running else 'STOPPED'}")

        # Site connectivity
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{SITE_URL}/lacie/", timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    lines.append(
                        f"Site `{SITE_URL}` — HTTP {resp.status}"
                    )
        except Exception as e:
            lines.append(f"Site `{SITE_URL}` — UNREACHABLE: {e}")

        # Bot uptime approximation via first connected guild
        lines.append(f"Guilds cached: {len(self.bot.guilds)}")

        embed = discord.Embed(
            title="System Health",
            description="\n".join(lines),
            color=EVENT_COLOR,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @system_group.command(
        name="schedule",
        description="Preview the next N scheduled Discord posts with exact UTC times",
    )
    @app_commands.describe(count="Number of upcoming posts to show (default 7)")
    async def system_schedule(self, interaction: discord.Interaction, count: int = 7):
        if not _check_owner(interaction):
            await interaction.response.send_message("No.", ephemeral=True)
            return

        cfg = _load_config()
        post_h = cfg["post_time_utc"]["hour"]
        post_m = cfg["post_time_utc"]["minute"]
        start = date.fromisoformat(cfg["event_start_date"])
        end = date.fromisoformat(cfg["event_end_date"])
        reveal = date.fromisoformat(cfg["reveal_date"])
        now = datetime.now(timezone.utc)

        lines = []
        shown = 0

        # Event week posts
        for day_offset in range(7):
            post_date = start + timedelta(days=day_offset)
            post_dt = datetime(
                post_date.year, post_date.month, post_date.day,
                post_h, post_m, 0, tzinfo=timezone.utc,
            )
            day_num = day_offset + 1
            status = "upcoming" if post_dt > now else "past"
            lines.append(
                f"`{post_dt.strftime('%Y-%m-%d %H:%M UTC')}` "
                f"Day {day_num} capsule + puzzle post [{status}]"
            )
            shown += 1
            if shown >= count:
                break

        # Reveal
        if shown < count:
            reveal_dt = datetime(
                reveal.year, reveal.month, reveal.day,
                17, 0, 0, tzinfo=timezone.utc,
            )
            status = "upcoming" if reveal_dt > now else "past"
            lines.append(
                f"`{reveal_dt.strftime('%Y-%m-%d %H:%M UTC')}` "
                f"Capsule reveal DMs [{status}]"
            )

        embed = discord.Embed(
            title="Scheduled Posts",
            description="\n".join(lines),
            color=EVENT_COLOR,
        )
        embed.set_footer(text="All times UTC  \u00b7  noon EDT = 16:00 UTC")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminEvents(bot))
