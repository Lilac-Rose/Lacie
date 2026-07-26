import json
import sqlite3
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, time, timezone, date
from pathlib import Path

from embed.embed_color import get_embed_color
from utils.constants import GUILD_ID
from utils.logger import get_logger

logger = get_logger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "capsule_puzzle_config.json"
DB_PATH = Path(__file__).parent.parent / "data" / "puzzle.db"

EVENT_COLOR = 0xB48EAD

DAILY_ROLE_TEMPLATE = "5th Anni Event - Day {day} Solver"
PUZZLE_HUNTER_ROLE_NAME = "5th Anni Event - Puzzle Hunter"


def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _event_day(cfg: dict) -> int | None:
    """Return today's day number (1-7) if we're in the event window, else None."""
    today = date.today()
    start = date.fromisoformat(cfg["event_start_date"])
    end = date.fromisoformat(cfg["event_end_date"])
    if start <= today <= end:
        return (today - start).days + 1
    return None


def _puzzle_for_day(cfg: dict, day: int) -> dict | None:
    for puzzle in cfg["puzzles"]:
        if puzzle["day"] == day:
            return puzzle
    return None


class PuzzleHunt(commands.Cog):
    """Manages the 5th Anniversary ARG Puzzle Hunt (Aug 16-22, 2026).

    Fragment submission and role granting happens entirely on the website.
    This cog handles: daily lead-in Discord posts, leaderboard, and role
    pre-creation so the site can look up role IDs from puzzle_roles.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cfg = _load_config()
        self._init_db()
        self.daily_puzzle_post.start()

    async def cog_load(self):
        """Async setup: create event roles and store IDs in puzzle_roles."""
        await self._ensure_roles()

    async def cog_unload(self):
        self.daily_puzzle_post.cancel()

    # ------------------------------------------------------------------ #
    # Database                                                             #
    # ------------------------------------------------------------------ #

    def _init_db(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS puzzle_solves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                day INTEGER NOT NULL,
                solved_at TEXT NOT NULL,
                is_first_solver INTEGER DEFAULT 0,
                UNIQUE(user_id, day)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS puzzle_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                day INTEGER NOT NULL,
                attempted_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS puzzle_roles (
                day INTEGER PRIMARY KEY,
                role_id INTEGER NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------ #
    # Role helpers                                                         #
    # ------------------------------------------------------------------ #

    async def _ensure_roles(self):
        """Create all event roles if missing and persist their IDs to puzzle_roles."""
        guild = self.bot.get_guild(GUILD_ID)
        if guild is None:
            logger.error("PuzzleHunt._ensure_roles: guild not found")
            return

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Day 1-7 solver roles
        for day in range(1, 8):
            name = DAILY_ROLE_TEMPLATE.format(day=day)
            role = await self._get_or_create_role(guild, name)
            if role:
                c.execute(
                    "INSERT OR REPLACE INTO puzzle_roles (day, role_id) VALUES (?, ?)",
                    (day, role.id),
                )

        # Puzzle Hunter role stored at day=0
        hunter_role = await self._get_or_create_role(guild, PUZZLE_HUNTER_ROLE_NAME)
        if hunter_role:
            c.execute(
                "INSERT OR REPLACE INTO puzzle_roles (day, role_id) VALUES (?, ?)",
                (0, hunter_role.id),
            )

        conn.commit()
        conn.close()
        logger.info("PuzzleHunt: event roles ensured and IDs persisted to puzzle_roles")

    async def _get_or_create_role(
        self, guild: discord.Guild, name: str
    ) -> discord.Role | None:
        role = discord.utils.get(guild.roles, name=name)
        if role is None:
            try:
                role = await guild.create_role(
                    name=name, reason="5th Anniversary Event"
                )
                logger.info(f"PuzzleHunt: created role '{name}'")
            except discord.Forbidden:
                logger.error(
                    f"PuzzleHunt: missing Manage Roles permission to create '{name}'"
                )
                return None
            except Exception as e:
                logger.error(f"PuzzleHunt: failed to create role '{name}': {e}")
                return None
        return role

    # ------------------------------------------------------------------ #
    # Scheduled task                                                       #
    # ------------------------------------------------------------------ #

    async def _post_daily_puzzle(self, day: int):
        """Post today's ARG lead-in message to #puzzle-hunt. Called by task and admin force-post."""
        self.cfg = _load_config()
        puzzle = _puzzle_for_day(self.cfg, day)
        if puzzle is None:
            logger.error(f"PuzzleHunt: no puzzle config found for day {day}")
            return

        channel_id = self.cfg["puzzle_channel_id"]
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            logger.error(f"PuzzleHunt: channel {channel_id} not found")
            return

        page_url = puzzle["page_url"]
        full_url = f"https://bots.lilacrose.dev{page_url}"

        embed = discord.Embed(
            description=f"{puzzle['discord_message']}\n\n[investigate]({full_url})",
            color=EVENT_COLOR,
        )
        embed.set_footer(
            text=f"5th Anniversary Puzzle Hunt  \u00b7  Day {day} of 7  \u00b7  Aug 16-22, 2026"
        )
        await channel.send(embed=embed)
        logger.info(f"PuzzleHunt: posted Day {day} lead-in")

    @tasks.loop(
        time=time(hour=16, minute=0, tzinfo=timezone.utc)  # noon EDT (UTC-4)
    )
    async def daily_puzzle_post(self):
        self.cfg = _load_config()
        day = _event_day(self.cfg)
        if day is None:
            return
        await self._post_daily_puzzle(day)

    @daily_puzzle_post.before_loop
    async def before_daily_puzzle(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ #
    # Slash commands                                                       #
    # ------------------------------------------------------------------ #

    puzzle_group = app_commands.Group(
        name="puzzle",
        description="5th Anniversary Puzzle Hunt commands",
    )

    @puzzle_group.command(
        name="today",
        description="Show today's puzzle lead-in and link",
    )
    async def puzzle_today(self, interaction: discord.Interaction):
        self.cfg = _load_config()
        day = _event_day(self.cfg)
        if day is None:
            await interaction.response.send_message(
                "The Puzzle Hunt isn't active right now (Aug 16-22, 2026).",
                ephemeral=True,
            )
            return

        puzzle = _puzzle_for_day(self.cfg, day)
        if puzzle is None:
            await interaction.response.send_message(
                "No puzzle found for today. Let a mod know!", ephemeral=True
            )
            return

        page_url = puzzle["page_url"]
        full_url = f"https://bots.lilacrose.dev{page_url}"

        embed = discord.Embed(
            description=f"{puzzle['discord_message']}\n\n[investigate]({full_url})",
            color=get_embed_color(interaction.user.id),
        )
        embed.set_footer(
            text=f"Day {day} of 7  \u00b7  5th Anniversary Puzzle Hunt"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @puzzle_group.command(
        name="leaderboard",
        description="See who's solved the most puzzles this week",
    )
    async def puzzle_leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT user_id, COUNT(*) as solve_count
            FROM puzzle_solves
            GROUP BY user_id
            ORDER BY solve_count DESC
            LIMIT 15
        """)
        rows = c.fetchall()
        conn.close()

        if not rows:
            await interaction.followup.send("No puzzles solved yet — be the first!")
            return

        lines = []
        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        for i, (user_id, count) in enumerate(rows):
            user = self.bot.get_user(user_id)
            name = user.display_name if user else f"User {user_id}"
            prefix = medals[i] if i < 3 else f"`{i + 1}.`"
            plural = "puzzle" if count == 1 else "puzzles"
            lines.append(f"{prefix} **{name}** — {count} {plural} solved")

        embed = discord.Embed(
            title="Puzzle Hunt — Leaderboard",
            description="\n".join(lines),
            color=get_embed_color(interaction.user.id),
        )
        embed.set_footer(text="5th Anniversary Event  \u00b7  Aug 16-22, 2026")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(PuzzleHunt(bot))
