import json
import sqlite3
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, date, timezone
from collections import defaultdict
from pathlib import Path
from utils.constants import GUILD_ID
from utils.logger import get_logger

logger = get_logger(__name__)

CONFIG_PATH     = Path(__file__).parent / "config.json"
LEAGUES_DB_PATH = Path(__file__).parent.parent / "data" / "leagues.db"
CAPSULE_DB_PATH = Path(__file__).parent.parent / "data" / "capsule.db"
PUZZLE_DB_PATH  = Path(__file__).parent.parent / "data" / "puzzle.db"

EVENT_COLOR = 0xB48EAD

TIER_COLORS = {
    "easy":   0x88C0D0,
    "medium": 0xA3BE8C,
    "hard":   0xD08770,
    "elite":  0xBF616A,
}
TIER_LABELS = {
    "easy": "Easy", "medium": "Medium", "hard": "Hard", "elite": "Elite"
}


def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _event_active(cfg: dict) -> bool:
    now   = datetime.now(timezone.utc)
    pt    = cfg.get("post_time_utc", {})
    start = datetime.fromisoformat(cfg["event_start_date"]).replace(
        hour=pt.get("hour", 16), minute=pt.get("minute", 0),
        second=0, microsecond=0, tzinfo=timezone.utc,
    )
    end   = datetime.fromisoformat(cfg["event_end_date"]).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc,
    )
    return start <= now <= end


def _event_day_key(cfg: dict) -> str:
    """Return the current event day number (1-7) as a string, using 16:00 UTC boundaries."""
    now = datetime.now(timezone.utc)
    pt  = cfg.get("post_time_utc", {})
    start = datetime.fromisoformat(cfg["event_start_date"]).replace(
        hour=pt.get("hour", 16), minute=pt.get("minute", 0),
        second=0, microsecond=0, tzinfo=timezone.utc,
    )
    return str(int((now - start).total_seconds() // 86400) + 1)


class LeaderboardView(discord.ui.View):
    def __init__(self, cog, ranked: list, page: int, total_pages: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.ranked = ranked
        self.page = page
        self.total_pages = total_pages
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.page <= 1
        self.next_btn.disabled = self.page >= self.total_pages

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        embed = self.cog._build_leaderboard_embed(self.ranked, interaction.guild, self.page, self.total_pages)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        embed = self.cog._build_leaderboard_embed(self.ranked, interaction.guild, self.page, self.total_pages)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class Leagues(commands.Cog):
    """
    5th Anniversary leagues system.
    Tracks 35 tasks across Easy/Medium/Hard/Elite tiers and grants roles at
    point thresholds. Listens to Discord events and checks cross-DB state.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._init_db()

    async def cog_load(self):
        self._startup.start()

    async def cog_unload(self):
        self._startup.cancel()
        self._periodic_check.cancel()

    # ------------------------------------------------------------------ #
    # Startup                                                               #
    # ------------------------------------------------------------------ #

    @tasks.loop(count=1)
    async def _startup(self):
        await self.bot.wait_until_ready()
        await self._ensure_roles()
        self._periodic_check.start()

    # ------------------------------------------------------------------ #
    # Database                                                             #
    # ------------------------------------------------------------------ #

    def _init_db(self):
        LEAGUES_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS leagues_completions (
                user_id INTEGER NOT NULL,
                task_id TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (user_id, task_id)
            )
        """)
        # event_key: ISO date for day-counting tasks, puzzle day str for page views,
        # 'done' for one-time tasks
        c.execute("""
            CREATE TABLE IF NOT EXISTS leagues_discord_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                event_key TEXT NOT NULL,
                UNIQUE(user_id, event_type, event_key)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS showcase_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                caption TEXT,
                image_url TEXT NOT NULL,
                message_id INTEGER,
                submitted_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS shoutout_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER NOT NULL,
                to_user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                UNIQUE(from_user_id, to_user_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS leagues_roles (
                threshold INTEGER PRIMARY KEY,
                role_id INTEGER NOT NULL,
                role_name TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_cache (
                user_id INTEGER PRIMARY KEY,
                display_name TEXT NOT NULL,
                username TEXT NOT NULL,
                avatar_url TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def _cache_user(self, user: discord.User | discord.Member):
        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()
        try:
            c.execute(
                """INSERT INTO user_cache (user_id, display_name, username, avatar_url, updated_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     display_name=excluded.display_name,
                     username=excluded.username,
                     avatar_url=excluded.avatar_url,
                     updated_at=excluded.updated_at""",
                (user.id, user.display_name, user.name,
                 str(user.display_avatar.url) if user.display_avatar else None,
                 datetime.utcnow().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def _record_event(self, user_id: int, event_type: str, event_key: str):
        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()
        try:
            c.execute(
                "INSERT OR IGNORE INTO leagues_discord_events (user_id, event_type, event_key) VALUES (?,?,?)",
                (user_id, event_type, event_key),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # Role management                                                       #
    # ------------------------------------------------------------------ #

    async def _ensure_roles(self):
        cfg = _load_config()
        guild = self.bot.get_guild(GUILD_ID)
        if guild is None:
            return

        _stale_role_names = [
            "5th Anni Event - Initiate",
            "5th Anni Event - Seeker",
            "5th Anni Event - Devotee",
            "5th Anni Event - Ardent",
            "5th Anni Event - Legend",
        ]
        for stale_name in _stale_role_names:
            stale = discord.utils.get(guild.roles, name=stale_name)
            if stale is not None:
                try:
                    await stale.delete(reason="5th Anniversary Leagues: removed old role name")
                    logger.info(f"Leagues: deleted stale role '{stale_name}'")
                except Exception as e:
                    logger.error(f"Leagues: failed to delete stale role '{stale_name}': {e}")

        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()
        for entry in cfg.get("leagues_roles", []):
            name = entry["name"]
            threshold = entry["threshold"]
            # Look up by stored ID first so we can rename stale roles
            c.execute("SELECT role_id FROM leagues_roles WHERE threshold=?", (threshold,))
            row = c.fetchone()
            existing = guild.get_role(row[0]) if row else None
            if existing is None:
                existing = discord.utils.get(guild.roles, name=name)
            if existing is not None and existing.name != name:
                try:
                    await existing.edit(name=name, reason="5th Anniversary Leagues role rename")
                    logger.info(f"Leagues: renamed role to '{name}'")
                except Exception as e:
                    logger.error(f"Leagues: failed to rename role '{existing.name}': {e}")
            if existing is None:
                try:
                    existing = await guild.create_role(name=name, reason="5th Anniversary Leagues")
                    logger.info(f"Leagues: created role '{name}'")
                except Exception as e:
                    logger.error(f"Leagues: failed to create role '{name}': {e}")
                    continue
            c.execute(
                "INSERT OR REPLACE INTO leagues_roles (threshold, role_id, role_name) VALUES (?,?,?)",
                (threshold, existing.id, name),
            )
        conn.commit()
        conn.close()

    async def _grant_new_roles(self, user_id: int, points: int, guild: discord.Guild):
        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT threshold, role_id FROM leagues_roles ORDER BY threshold ASC")
        role_rows = c.fetchall()
        conn.close()

        member = guild.get_member(user_id)
        if member is None:
            return

        for threshold, role_id in role_rows:
            if points >= threshold:
                role = guild.get_role(role_id)
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason="5th Anniversary Leagues threshold reached")
                        logger.info(f"Leagues: granted '{role.name}' to {user_id} ({points} pts)")
                    except Exception as e:
                        logger.error(f"Leagues: failed to grant role to {user_id}: {e}")

    # ------------------------------------------------------------------ #
    # Task checking                                                         #
    # ------------------------------------------------------------------ #

    def _gather_state(self, user_id: int) -> dict:
        s = {}

        if CAPSULE_DB_PATH.exists():
            conn = sqlite3.connect(CAPSULE_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT day, submitted_at FROM capsule_submissions WHERE user_id=?", (user_id,))
            rows = c.fetchall()
            conn.close()
            s["capsule_days"] = {r[0] for r in rows}
            s["capsule_submissions"] = rows
        else:
            s["capsule_days"] = set()
            s["capsule_submissions"] = []

        if PUZZLE_DB_PATH.exists():
            conn = sqlite3.connect(PUZZLE_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT day, solved_at FROM puzzle_solves WHERE user_id=?", (user_id,))
            solve_rows = c.fetchall()
            c.execute("SELECT day FROM puzzle_attempts WHERE user_id=?", (user_id,))
            attempt_rows = c.fetchall()
            conn.close()
            s["puzzle_solved_days"] = {r[0] for r in solve_rows}
            s["puzzle_solves"] = solve_rows
            s["puzzle_attempt_puzzle_days"] = {r[0] for r in attempt_rows}
        else:
            s["puzzle_solved_days"] = set()
            s["puzzle_solves"] = []
            s["puzzle_attempt_puzzle_days"] = set()

        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT event_type, event_key FROM leagues_discord_events WHERE user_id=?", (user_id,))
        events = c.fetchall()
        c.execute("SELECT COUNT(*) FROM showcase_submissions WHERE user_id=?", (user_id,))
        s["showcase_count"] = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT to_user_id) FROM shoutout_submissions WHERE from_user_id=?", (user_id,))
        s["shoutout_unique"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM shoutout_submissions WHERE to_user_id=?", (user_id,))
        s["shoutout_received"] = c.fetchone()[0]
        conn.close()

        event_keys = defaultdict(set)
        for event_type, event_key in events:
            event_keys[event_type].add(event_key)
        s["event_keys"] = event_keys

        return s

    def _same_day_capsule_and_solve(self, s: dict) -> bool:
        capsule_days = {str(r[0]) for r in s["capsule_submissions"]}
        solve_days   = {str(r[0]) for r in s["puzzle_solves"]}
        return bool(capsule_days & solve_days)

    def _has_consecutive_capsule_days(self, s: dict, n: int = 3) -> bool:
        days = sorted(s["capsule_days"])
        for i in range(len(days) - n + 1):
            if days[i + n - 1] == days[i] + n - 1:
                return True
        return False

    def _has_consecutive_solve_days(self, s: dict, n: int = 3) -> bool:
        days = sorted(s["puzzle_solved_days"])
        for i in range(len(days) - n + 1):
            if days[i + n - 1] == days[i] + n - 1:
                return True
        return False

    def _condition_met(self, task_id: str, s: dict) -> bool:
        ek = s["event_keys"]
        return {
            "submit_capsule_any":        len(s["capsule_days"]) >= 1,
            "puzzle_attempt_any":        len(s["puzzle_attempt_puzzle_days"]) >= 1,
            "submit_shoutout":           s["shoutout_unique"] >= 1,
            "submit_showcase":           s["showcase_count"] >= 1,
            "site_login":                "done" in ek.get("site_login", set()),
            "use_puzzle_today":          "done" in ek.get("puzzle_today", set()),
            "use_capsule_count":         "done" in ek.get("capsule_count", set()),
            "react_capsule_any":         len(ek.get("capsule_react", set())) >= 1,
            "react_showcase_any":        len(ek.get("showcase_react", set())) >= 1,
            "post_puzzle_hunt_any":      len(ek.get("puzzle_hunt_message", set())) >= 1,
            "puzzle_attempt_2days":      len(s["puzzle_attempt_puzzle_days"]) >= 2,
            "view_puzzle_page":          len(ek.get("puzzle_page_view", set())) >= 1,

            "solve_any":                 len(s["puzzle_solved_days"]) >= 1,
            "capsule_3days":             len(s["capsule_days"]) >= 3,
            "visit_all_puzzles":         len(ek.get("puzzle_page_view", set())) >= 7,
            "shoutout_2people":          s["shoutout_unique"] >= 2,
            "capsule_day1":              1 in s["capsule_days"],
            "capsule_day7":              7 in s["capsule_days"],
            "puzzle_attempt_3days":      len(s["puzzle_attempt_puzzle_days"]) >= 3,
            "react_capsule_3days":       len(ek.get("capsule_react", set())) >= 3,
            "post_puzzle_hunt_3days":    len(ek.get("puzzle_hunt_message", set())) >= 3,
            "showcase_and_attempt":      s["showcase_count"] >= 1 and len(s["puzzle_attempt_puzzle_days"]) >= 1,

            "solve_day5":                5 in s["puzzle_solved_days"],
            "solve_3plus":               len(s["puzzle_solved_days"]) >= 3,
            "capsule_5days":             len(s["capsule_days"]) >= 5,
            "capsule_and_solve_same_day":self._same_day_capsule_and_solve(s),
            "shoutout_3people":          s["shoutout_unique"] >= 3,
            "puzzle_attempt_5days":      len(s["puzzle_attempt_puzzle_days"]) >= 5,
            "react_capsule_5days":       len(ek.get("capsule_react", set())) >= 5,
            "showcase_and_solve":        s["showcase_count"] >= 1 and len(s["puzzle_solved_days"]) >= 1,

            "solve_day7":                7 in s["puzzle_solved_days"],
            "solve_all":                 len(s["puzzle_solved_days"]) >= 7,
            "capsule_all":               len(s["capsule_days"]) >= 7,
            "solve_5plus":               len(s["puzzle_solved_days"]) >= 5,
            "everything":                len(s["capsule_days"]) >= 7 and len(s["puzzle_solved_days"]) >= 3,

            # new easy
            "puzzle_solve_day1":         1 in s["puzzle_solved_days"],
            "shoutout_received":         s["shoutout_received"] >= 1,
            "react_capsule_day1":        "1" in ek.get("capsule_react", set()),

            # new medium
            "solve_2plus":               len(s["puzzle_solved_days"]) >= 2,
            "capsule_4days":             len(s["capsule_days"]) >= 4,
            "react_showcase_3":          len(ek.get("showcase_react", set())) >= 3,
            "puzzle_attempt_all7":       len(s["puzzle_attempt_puzzle_days"]) >= 7,

            # new hard
            "solve_4plus":               len(s["puzzle_solved_days"]) >= 4,
            "shoutout_received_2":       s["shoutout_received"] >= 2,
            "capsule_consecutive_3":     self._has_consecutive_capsule_days(s, 3),
            "capsule_showcase_shoutout": len(s["capsule_days"]) >= 1 and s["showcase_count"] >= 1 and s["shoutout_unique"] >= 1,

            # new elite
            "solve_6plus":               len(s["puzzle_solved_days"]) >= 6,
            "react_capsule_all7":        all(str(d) in ek.get("capsule_react", set()) for d in range(1, 8)),

            # site page visits (recorded via server.py when logged in)
            "visit_home_page":           "home" in ek.get("page_view", set()),
            "visit_capsule_page":        "capsule" in ek.get("page_view", set()),
            "visit_countdown_page":      "countdown" in ek.get("page_view", set()),
            "visit_showcase_page":       "showcase" in ek.get("page_view", set()),
            "visit_shoutout_page":       "shoutouts" in ek.get("page_view", set()),
            "visit_puzzle_archive_page": "puzzle_archive" in ek.get("page_view", set()),
            "visit_leagues_page":        "leagues" in ek.get("page_view", set()),
            "visit_all_site_pages":      all(p in ek.get("page_view", set()) for p in
                                             ["home", "capsule", "countdown", "showcase",
                                              "shoutouts", "puzzle_archive", "leagues"]),

            # discord general chat
            "post_general_any":          len(ek.get("chat_message", set())) >= 1,
            "post_general_3days":        len(ek.get("chat_message", set())) >= 3,
            "post_general_5days":        len(ek.get("chat_message", set())) >= 5,
            "post_general_all7":         len(ek.get("chat_message", set())) >= 7,

            # voice channel activity
            "voice_join_any":            len(ek.get("voice_join", set())) >= 1,
            "voice_3days":               len(ek.get("voice_join", set())) >= 3,
            "voice_5days":               len(ek.get("voice_join", set())) >= 5,
            "voice_all7":                len(ek.get("voice_join", set())) >= 7,

            # image/attachment posting
            "post_image_any":            len(ek.get("image_post", set())) >= 1,

            # specific puzzle day solves
            "solve_day2":                2 in s["puzzle_solved_days"],
            "solve_day3":                3 in s["puzzle_solved_days"],
            "solve_day4":                4 in s["puzzle_solved_days"],
            "solve_day6":                6 in s["puzzle_solved_days"],

            # specific capsule days
            "capsule_day2":              2 in s["capsule_days"],
            "capsule_day3":              3 in s["capsule_days"],
            "capsule_day4":              4 in s["capsule_days"],
            "capsule_day5":              5 in s["capsule_days"],
            "capsule_day6":              6 in s["capsule_days"],

            # showcase progression
            "showcase_2":                s["showcase_count"] >= 2,
            "showcase_3":                s["showcase_count"] >= 3,

            # react progression
            "react_showcase_5":          len(ek.get("showcase_react", set())) >= 5,
            "react_capsule_day7":        "7" in ek.get("capsule_react", set()),

            # shoutout sent progression
            "shoutout_4people":          s["shoutout_unique"] >= 4,
            "shoutout_5plus":            s["shoutout_unique"] >= 5,

            # shoutout received progression
            "shoutout_received_3":       s["shoutout_received"] >= 3,
            "shoutout_received_5":       s["shoutout_received"] >= 5,

            # puzzle discussion engagement
            "post_puzzle_hunt_5days":    len(ek.get("puzzle_hunt_message", set())) >= 5,
            "post_puzzle_hunt_all7":     len(ek.get("puzzle_hunt_message", set())) >= 7,

            # consecutive solve days
            "solve_consecutive_3":       self._has_consecutive_solve_days(s, 3),

            # cross-feature combos using general chat / voice
            "post_general_and_puzzle_same_day": bool(
                ek.get("chat_message", set()) & ek.get("puzzle_hunt_message", set())),
            "capsule_and_general_same_day": bool(
                {str(r[0]) for r in s["capsule_submissions"]} & ek.get("chat_message", set())),
            "voice_and_capsule_same_day": bool(
                {str(r[0]) for r in s["capsule_submissions"]} & ek.get("voice_join", set())),

            # all-in social elite
            "social_butterfly":          len(s["capsule_days"]) >= 7 and s["shoutout_unique"] >= 5
                                         and s["showcase_count"] >= 1,
        }.get(task_id, False)

    def _check_tasks(self, user_id: int) -> list[str]:
        """Check all tasks for user, mark newly completed ones, return their IDs."""
        cfg = _load_config()
        s = self._gather_state(user_id)
        tasks_cfg = cfg.get("leagues_tasks", [])

        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT task_id FROM leagues_completions WHERE user_id=?", (user_id,))
        already_done = {r[0] for r in c.fetchall()}

        newly_completed = []
        for task in tasks_cfg:
            tid = task["task_id"]
            if tid in already_done:
                continue
            if self._condition_met(tid, s):
                c.execute(
                    "INSERT OR IGNORE INTO leagues_completions (user_id, task_id, completed_at) VALUES (?,?,?)",
                    (user_id, tid, datetime.utcnow().isoformat()),
                )
                newly_completed.append(tid)

        conn.commit()
        conn.close()
        return newly_completed

    def _get_user_points(self, user_id: int) -> int:
        cfg = _load_config()
        task_points = {t["task_id"]: t["points"] for t in cfg.get("leagues_tasks", [])}
        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT task_id FROM leagues_completions WHERE user_id=?", (user_id,))
        completed = {r[0] for r in c.fetchall()}
        conn.close()
        return sum(task_points.get(tid, 0) for tid in completed)

    # ------------------------------------------------------------------ #
    # Listeners                                                            #
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_leagues_event(self, user_id: int, event_type: str, event_key: str,
                               user: discord.User | discord.Member | None = None):
        """Record a specific Discord event and check tasks."""
        cfg = _load_config()
        if not _event_active(cfg):
            return
        if user:
            self._cache_user(user)
        self._record_event(user_id, event_type, event_key)
        newly = self._check_tasks(user_id)
        if newly:
            await self._process_completions(user_id, newly)

    @commands.Cog.listener()
    async def on_leagues_action(self, user_id: int, action: str,
                                user: discord.User | discord.Member | None = None):
        cfg = _load_config()
        if not _event_active(cfg):
            return
        if user:
            self._cache_user(user)
        newly = self._check_tasks(user_id)
        if newly:
            await self._process_completions(user_id, newly)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        cfg = _load_config()
        if not _event_active(cfg):
            return

        self._cache_user(message.author)
        today = _event_day_key(cfg)
        newly = []

        puzzle_channel_id    = cfg.get("puzzle_channel_id")
        chat_channel_ids     = {cfg.get("chat_channel_id"), cfg.get("anniversary_chat_channel_id")} - {None}

        puzzle_discussion_channel_id = cfg.get("puzzle_discussion_channel_id")
        puzzle_spoilers_channel_id   = cfg.get("puzzle_spoilers_channel_id")
        if message.channel.id in {puzzle_discussion_channel_id, puzzle_spoilers_channel_id} - {None}:
            self._record_event(message.author.id, "puzzle_hunt_message", today)
            newly += self._check_tasks(message.author.id)

        if message.channel.id in chat_channel_ids:
            self._record_event(message.author.id, "chat_message", today)
            newly += self._check_tasks(message.author.id)

        if message.attachments:
            self._record_event(message.author.id, "image_post", today)
            newly += self._check_tasks(message.author.id)

        if newly:
            await self._process_completions(message.author.id, list(dict.fromkeys(newly)))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        user = guild.get_member(payload.user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(payload.user_id)
            except Exception:
                return
        if user.bot:
            return

        cfg = _load_config()
        if not _event_active(cfg):
            return

        self._cache_user(user)
        today = _event_day_key(cfg)
        newly = []

        # Check capsule post reactions — store day number so we can check specific days
        if CAPSULE_DB_PATH.exists():
            conn = sqlite3.connect(CAPSULE_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT day FROM capsule_post_messages WHERE message_id=?", (payload.message_id,))
            row = c.fetchone()
            conn.close()
            if row:
                self._record_event(payload.user_id, "capsule_react", str(row[0]))
                newly += self._check_tasks(payload.user_id)

        # Check showcase post reactions (don't count reacting to your own post)
        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id FROM showcase_submissions WHERE message_id=?", (payload.message_id,))
        row = c.fetchone()
        conn.close()
        if row and row[0] != payload.user_id:
            self._record_event(payload.user_id, "showcase_react", str(payload.message_id))
            newly += self._check_tasks(payload.user_id)

        if newly:
            await self._process_completions(payload.user_id, newly)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
                                    before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        if after.channel is None:
            return  # leaving voice, not joining
        cfg = _load_config()
        if not _event_active(cfg):
            return
        self._cache_user(member)
        today = _event_day_key(cfg)
        self._record_event(member.id, "voice_join", today)
        newly = self._check_tasks(member.id)
        if newly:
            await self._process_completions(member.id, newly)

    async def _process_completions(self, user_id: int, newly_completed: list[str]):
        cfg = _load_config()
        points = self._get_user_points(user_id)
        guild = self.bot.get_guild(GUILD_ID)
        if guild:
            await self._grant_new_roles(user_id, points, guild)

    # ------------------------------------------------------------------ #
    # Background task — catch puzzle solves that come from the website     #
    # ------------------------------------------------------------------ #

    @tasks.loop(seconds=60)
    async def _periodic_check(self):
        cfg = _load_config()
        if not _event_active(cfg):
            return

        # Gather all users with any activity across all sources
        user_ids: set[int] = set()

        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT DISTINCT user_id FROM leagues_discord_events")
        user_ids.update(r[0] for r in c.fetchall())
        c.execute("SELECT DISTINCT user_id FROM leagues_completions")
        user_ids.update(r[0] for r in c.fetchall())
        c.execute("SELECT DISTINCT from_user_id FROM shoutout_submissions")
        user_ids.update(r[0] for r in c.fetchall())
        c.execute("SELECT DISTINCT to_user_id FROM shoutout_submissions")
        user_ids.update(r[0] for r in c.fetchall())
        c.execute("SELECT DISTINCT user_id FROM showcase_submissions")
        user_ids.update(r[0] for r in c.fetchall())
        conn.close()

        if PUZZLE_DB_PATH.exists():
            conn = sqlite3.connect(PUZZLE_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT DISTINCT user_id FROM puzzle_solves")
            user_ids.update(r[0] for r in c.fetchall())
            conn.close()

        if CAPSULE_DB_PATH.exists():
            conn = sqlite3.connect(CAPSULE_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT DISTINCT user_id FROM capsule_submissions")
            user_ids.update(r[0] for r in c.fetchall())
            conn.close()

        guild = self.bot.get_guild(GUILD_ID)
        for user_id in user_ids:
            newly = self._check_tasks(user_id)
            if newly and guild:
                points = self._get_user_points(user_id)
                await self._grant_new_roles(user_id, points, guild)

    # ------------------------------------------------------------------ #
    # Commands                                                             #
    # ------------------------------------------------------------------ #

    leagues_group = app_commands.Group(name="leagues", description="5th Anniversary Leagues")

    @leagues_group.command(name="card", description="See your current leagues progress")
    async def leagues_card(self, interaction: discord.Interaction):
        cfg = _load_config()
        tasks_cfg = cfg.get("leagues_tasks", [])

        # Run check first so progress is up to date
        newly = self._check_tasks(interaction.user.id)
        if newly:
            await self._process_completions(interaction.user.id, newly)

        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT task_id FROM leagues_completions WHERE user_id=?", (interaction.user.id,))
        completed = {r[0] for r in c.fetchall()}
        c.execute("SELECT threshold, role_name FROM leagues_roles ORDER BY threshold ASC")
        role_rows = c.fetchall()
        conn.close()

        points = sum(t["points"] for t in tasks_cfg if t["task_id"] in completed)
        total  = sum(t["points"] for t in tasks_cfg)

        embed = discord.Embed(
            title="Your Leagues Card",
            color=EVENT_COLOR,
        )
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url,
        )
        embed.description = f"**{points} / {total} pts**"

        # Next threshold
        next_threshold = next((r for r in role_rows if points < r[0]), None)
        if next_threshold:
            embed.description += f"  •  {next_threshold[0] - points} pts until **{next_threshold[1]}**"

        # Tasks by tier
        by_tier = defaultdict(list)
        for task in tasks_cfg:
            by_tier[task["tier"]].append(task)

        for tier in ("easy", "medium", "hard", "elite"):
            tier_tasks = by_tier[tier]
            done_count = sum(1 for t in tier_tasks if t["task_id"] in completed)
            pts_in_tier = sum(t["points"] for t in tier_tasks)
            done_pts    = sum(t["points"] for t in tier_tasks if t["task_id"] in completed)

            lines = []
            for task in tier_tasks:
                check = "✓" if task["task_id"] in completed else "○"
                lines.append(f"{check} {task['name']} *({task['points']} pt{'s' if task['points'] > 1 else ''})*")

            embed.add_field(
                name=f"{TIER_LABELS[tier]}  —  {done_pts}/{pts_in_tier} pts  ({done_count}/{len(tier_tasks)})",
                value="\n".join(lines),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    def _build_leaderboard_embed(self, ranked: list, guild: discord.Guild, page: int, total_pages: int) -> discord.Embed:
        PER_PAGE = 10
        offset = (page - 1) * PER_PAGE
        page_slice = ranked[offset : offset + PER_PAGE]
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (user_id, pts) in enumerate(page_slice):
            rank = offset + i
            prefix = medals[rank] if rank < 3 else f"**{rank + 1}.**"
            member = guild.get_member(user_id)
            name = discord.utils.escape_markdown(member.display_name if member else f"User {user_id}")
            lines.append(f"{prefix} {name} — {pts} pts")
        embed = discord.Embed(title="Leagues Leaderboard — Final", color=EVENT_COLOR)
        embed.description = "\n".join(lines) if lines else "No scores yet!"
        embed.set_footer(text=f"Page {page}/{total_pages}  ·  {len(ranked)} participants  ·  Event ended Aug 22, 2026  ·  Leaderboard is final")
        return embed

    @leagues_group.command(name="leaderboard", description="See the final leagues leaderboard")
    @app_commands.describe(page="Page number (10 players per page)")
    async def leagues_leaderboard(self, interaction: discord.Interaction, page: int = 1):
        cfg = _load_config()
        task_points = {t["task_id"]: t["points"] for t in cfg.get("leagues_tasks", [])}

        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id, task_id, completed_at FROM leagues_completions")
        rows = c.fetchall()
        conn.close()

        scores: dict[int, int] = defaultdict(int)
        last_completion: dict[int, str] = {}
        for user_id, task_id, completed_at in rows:
            scores[user_id] += task_points.get(task_id, 0)
            if completed_at and (user_id not in last_completion or completed_at > last_completion[user_id]):
                last_completion[user_id] = completed_at

        PER_PAGE = 10
        ranked = sorted(scores.items(), key=lambda x: (-x[1], last_completion.get(x[0], "")))
        total_pages = max(1, (len(ranked) + PER_PAGE - 1) // PER_PAGE)
        page = max(1, min(page, total_pages))

        embed = self._build_leaderboard_embed(ranked, interaction.guild, page, total_pages)
        view = LeaderboardView(self, ranked, page, total_pages)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Leagues(bot))
