import json
import random
import sqlite3
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, time, timezone, date
from pathlib import Path

LEAGUES_DB_PATH = Path(__file__).parent.parent / "data" / "leagues.db"

_DAY_TO_ROUND = {1: "r1", 2: "r2", 3: "qf", 4: "sf", 5: "final", 6: "final", 7: "final"}


def _bracket_round_match_ids(bracket: dict, round_name: str) -> list[tuple[str, dict]]:
    if round_name == "final":
        m = bracket.get("final", {})
        return [("final", m)] if m.get("a") and m.get("b") else []
    out = []
    for side in ("left", "right"):
        sd = bracket.get(side, {})
        rdata = sd.get(round_name)
        if rdata is None:
            continue
        if isinstance(rdata, list):
            for i, m in enumerate(rdata):
                out.append((f"{side}_{round_name}_{i}", m))
        else:
            out.append((f"{side}_{round_name}", rdata))
    return out

from embed.embed_color import get_embed_color
from utils.constants import GUILD_ID
from utils.logger import get_logger

logger = get_logger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.json"
DB_PATH = Path(__file__).parent.parent / "data" / "capsule.db"

EVENT_COLOR = 0xB48EAD


def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _event_day(cfg: dict) -> int | None:
    """Return today's day number (1-7) if we're in the event window, else None."""
    now   = datetime.now(timezone.utc)
    pt    = cfg.get("post_time_utc", {})
    start = datetime.fromisoformat(cfg["event_start_date"]).replace(
        hour=pt.get("hour", 16), minute=pt.get("minute", 0),
        second=0, microsecond=0, tzinfo=timezone.utc,
    )
    end = datetime.fromisoformat(cfg["event_end_date"]).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc,
    )
    if start <= now <= end:
        return min(7, int((now - start).total_seconds() // 86400) + 1)
    return None


# ---------------------------------------------------------------------------
# Modal
# ---------------------------------------------------------------------------

class CapsuleModal(discord.ui.Modal):
    def __init__(self, day: int, prompt: str, attachment_url: str | None, *, late: bool = False):
        super().__init__(title=f"Time Capsule \u2014 Day {day}")
        self.day = day
        self.attachment_url = attachment_url
        self.late = late
        self.response_input = discord.ui.TextInput(
            label="Your response",
            placeholder=prompt[:100],
            style=discord.TextStyle.long,
            max_length=1500,
            required=True,
        )
        self.add_item(self.response_input)

    async def on_submit(self, interaction: discord.Interaction):
        response_text = self.response_input.value.strip()

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute(
                """
                INSERT INTO capsule_submissions
                    (user_id, day, response_text, image_url, submitted_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    interaction.user.id,
                    self.day,
                    response_text,
                    self.attachment_url,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            await interaction.response.send_message(
                "You've already submitted for today! Each day only allows one entry.",
                ephemeral=True,
            )
            return
        conn.close()

        image_note = " Your image has been saved with your entry." if self.attachment_url else ""
        if self.late:
            followup = "Glad you could still add to it — better late than never ♡"
        else:
            followup = "Everything will be revealed on August 16, 2027. You can submit again tomorrow for the next prompt."
        await interaction.response.send_message(
            f"Your Day {self.day} capsule entry has been sealed.{image_note}\n{followup}",
            ephemeral=True,
        )
        logger.info(
            f"Capsule submission: user={interaction.user.id} day={self.day}"
        )
        interaction.client.dispatch("leagues_action", interaction.user.id, "capsule_submit", interaction.user)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class TimeCapsule(commands.Cog):
    """Manages the 5th Anniversary Time Capsule event (Aug 16-22, 2026)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cfg = _load_config()
        self._init_db()
        self.daily_capsule_post.start()
        self.reveal_capsule.start()

    async def cog_load(self):
        """On startup, re-grant the bot send permissions if the event is already active."""
        self.cfg = _load_config()
        if _event_day(self.cfg) is not None:
            await self._open_event_channels()

    async def cog_unload(self):
        self.daily_capsule_post.cancel()
        self.reveal_capsule.cancel()

    # ------------------------------------------------------------------ #
    # Database                                                             #
    # ------------------------------------------------------------------ #

    def _init_db(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS capsule_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                day INTEGER NOT NULL,
                response_text TEXT NOT NULL,
                image_url TEXT,
                submitted_at TEXT NOT NULL,
                UNIQUE(user_id, day)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS capsule_event_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS capsule_post_messages (
                day INTEGER PRIMARY KEY,
                message_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def _get_state(self, key: str) -> str | None:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT value FROM capsule_event_state WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

    def _set_state(self, key: str, value: str):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO capsule_event_state (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _get_prompt(self, day: int) -> str:
        """Return the prompt for a given day, checking admin overrides first."""
        override = self._get_state(f"capsule_prompt_override_{day}")
        if override:
            return override

        prompts = self.cfg["capsule_prompts"]
        prompt = prompts[day - 1]
        if prompt is None:
            # Day 7 wildcard — pick once and persist so all submissions see the same question
            stored = self._get_state("day7_wildcard")
            if stored:
                return stored
            chosen = random.choice(self.cfg["wildcard_questions"])
            self._set_state("day7_wildcard", chosen)
            return chosen
        return prompt

    # ------------------------------------------------------------------ #
    # Post helper (called by task + admin force-post)                     #
    # ------------------------------------------------------------------ #

    async def _post_daily_capsule(self, day: int):
        """Post the time-capsule prompt embed for the given day."""
        self.cfg = _load_config()
        channel_id = self.cfg["capsule_channel_id"]
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            logger.error(f"TimeCapsule: channel {channel_id} not found")
            return

        prompt = self._get_prompt(day)
        day_labels = [
            "DAY 1 OF 7", "DAY 2 OF 7", "DAY 3 OF 7", "DAY 4 OF 7",
            "DAY 5 OF 7", "DAY 6 OF 7", "DAY 7 OF 7",
        ]

        embed = discord.Embed(
            title=f"Time Capsule \u2014 {day_labels[day - 1]}",
            description=(
                f"{prompt}\n\n"
                "Use `/capsule submit` to seal your response. "
                "Attach an optional image with `/capsule submit image:`.\n\n"
                "Entries are sealed until **August 16, 2027**. "
                "Opt in to share a short public excerpt on the website when you submit."
            ),
            color=EVENT_COLOR,
        )
        embed.set_footer(text="5th Anniversary Event \u00b7 Aug 16\u201322, 2026")
        msg = await channel.send(embed=embed)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO capsule_post_messages (day, message_id, channel_id) VALUES (?,?,?)",
            (day, msg.id, channel.id),
        )
        conn.commit()
        conn.close()
        logger.info(f"TimeCapsule: posted Day {day} prompt (msg={msg.id})")

    # ------------------------------------------------------------------ #
    # Reveal helper (called by task + admin force-reveal)                 #
    # ------------------------------------------------------------------ #

    def _build_capsule_embed(self, user_id: int, display_name: str, rows: list, *, for_dm: bool) -> discord.Embed:
        prompts = self.cfg["capsule_prompts"]
        if for_dm:
            embed = discord.Embed(
                title="Your Time Capsule Has Been Opened",
                description=(
                    "A year ago, you sealed a message to your future self.\n"
                    "Here's everything you wrote during the 5th Anniversary Event."
                ),
                color=EVENT_COLOR,
            )
        else:
            embed = discord.Embed(
                title=display_name,
                color=EVENT_COLOR,
            )
        for day_num, response_text, image_url in rows:
            prompt_text = prompts[day_num - 1]
            if prompt_text is None:
                prompt_text = self._get_state("day7_wildcard") or "Wildcard"
            field_name = f"Day {day_num} \u2014 {prompt_text[:50]}"
            field_value = response_text[:1024]
            if image_url:
                field_value += f"\n[attached image]({image_url})"
            embed.add_field(name=field_name, value=field_value, inline=False)
        embed.set_footer(text="5th Anniversary Event \u00b7 Opened August 16, 2027")
        return embed

    async def _reveal_for_user(self, user_id: int):
        """DM a single user their full capsule."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT day, response_text, image_url FROM capsule_submissions"
            " WHERE user_id = ? ORDER BY day",
            (user_id,),
        )
        rows = c.fetchall()
        conn.close()

        if not rows:
            return

        user = self.bot.get_user(user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(user_id)
            except Exception:
                logger.warning(f"TimeCapsule reveal: could not fetch user {user_id}")
                return

        embed = self._build_capsule_embed(user_id, user.display_name, rows, for_dm=True)
        try:
            await user.send(embed=embed)
            logger.info(f"TimeCapsule reveal: DMed user {user_id}")
        except discord.Forbidden:
            logger.warning(f"TimeCapsule reveal: could not DM user {user_id} (DMs closed)")
        except Exception as e:
            logger.error(f"TimeCapsule reveal: error DMing {user_id}: {e}")

    async def _reveal_public(self, channel: discord.TextChannel, user_ids: list[int]):
        """Post every participant's capsule publicly in the channel."""
        import asyncio
        guild = channel.guild
        for user_id in user_ids:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute(
                "SELECT day, response_text, image_url FROM capsule_submissions"
                " WHERE user_id = ? ORDER BY day",
                (user_id,),
            )
            rows = c.fetchall()
            conn.close()
            if not rows:
                continue

            member = guild.get_member(user_id)
            display_name = member.display_name if member else f"User {user_id}"

            embed = self._build_capsule_embed(user_id, display_name, rows, for_dm=False)
            try:
                await channel.send(embed=embed)
            except Exception as e:
                logger.error(f"TimeCapsule public reveal: error posting {user_id}: {e}")
            await asyncio.sleep(1.5)

    # ------------------------------------------------------------------ #
    # Scheduled tasks                                                      #
    # ------------------------------------------------------------------ #

    async def _open_event_channels(self):
        """On day 1, unhide the anniversary category and set per-channel perms."""
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return
        category_name = self.cfg.get("anniversary_category_name", "5th Anniversary")
        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            logger.warning("_open_event_channels: category %r not found", category_name)
            return

        send_enabled = {
            self.cfg.get("puzzle_discussion_channel_id"),
            self.cfg.get("anniversary_chat_channel_id"),
            self.cfg.get("puzzle_spoilers_channel_id"),
        } - {None}
        everyone = guild.default_role
        bot_member = guild.me

        await category.set_permissions(everyone, view_channel=True)

        for ch in category.channels:
            # Always grant the bot send permission so it can post in any channel
            await ch.set_permissions(bot_member, view_channel=True, send_messages=True)
            if ch.id in send_enabled:
                await ch.set_permissions(everyone, view_channel=True, send_messages=True)
            else:
                await ch.set_permissions(everyone, view_channel=True, send_messages=False)

        logger.info("Anniversary channels opened for @everyone")

    async def _advance_bracket_round(self, round_name: str):
        """Tally bracket votes for a round, set winners, and advance the next round's slots."""
        self.cfg = _load_config()
        bracket = self.cfg.get("character_bracket", {})
        matches = _bracket_round_match_ids(bracket, round_name)

        if not LEAGUES_DB_PATH.exists():
            return

        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()

        for mid, m in matches:
            a, b = m.get("a"), m.get("b")
            if not a or not b or m.get("winner"):
                continue
            c.execute(
                "SELECT choice, COUNT(*) FROM bracket_votes WHERE match_id=? GROUP BY choice",
                (mid,),
            )
            counts = {row[0]: row[1] for row in c.fetchall()}
            winner = a if counts.get(a, 0) >= counts.get(b, 0) else b
            m["winner"] = winner

            # Advance winner into next round
            if round_name == "final":
                pass  # nothing to advance
            elif round_name == "sf":
                side = mid.split("_")[0]
                slot = "a" if side == "left" else "b"
                bracket["final"][slot] = winner
            elif round_name == "qf":
                side, _, idx_str = mid.rsplit("_", 2)
                idx = int(idx_str)
                slot = "a" if idx == 0 else "b"
                bracket[side]["sf"][slot] = winner
            elif round_name == "r2":
                side, _, idx_str = mid.rsplit("_", 2)
                idx = int(idx_str)
                qf_idx = idx // 2
                slot = "a" if idx % 2 == 0 else "b"
                bracket[side]["qf"][qf_idx][slot] = winner
            elif round_name == "r1":
                side, _, idx_str = mid.rsplit("_", 2)
                idx = int(idx_str)
                bracket[side]["r2"][idx]["b"] = winner

        conn.close()

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, indent=2)
        logger.info(f"Bracket: closed round '{round_name}' and advanced winners")

    @tasks.loop(time=time(hour=16, minute=0, tzinfo=timezone.utc))
    async def daily_capsule_post(self):
        """Post the daily time-capsule prompt at noon EDT."""
        self.cfg = _load_config()
        day = _event_day(self.cfg)
        if day is None:
            return
        if day == 1:
            await self._open_event_channels()

        # Auto-close yesterday's bracket round when the day changes
        prev_round = _DAY_TO_ROUND.get(day - 1)
        curr_round = _DAY_TO_ROUND.get(day)
        if prev_round and curr_round and prev_round != curr_round:
            await self._advance_bracket_round(prev_round)

        await self._post_daily_capsule(day)

    @tasks.loop(time=time(hour=17, minute=0, tzinfo=timezone.utc))
    async def reveal_capsule(self):
        """On Aug 16, 2027, DM every participant their full capsule."""
        today = date.today()
        reveal = date.fromisoformat(self.cfg["reveal_date"])
        if today != reveal:
            return

        if self._get_state("reveal_done") == "1":
            return
        self._set_state("reveal_done", "1")

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT DISTINCT user_id FROM capsule_submissions")
        user_ids = [row[0] for row in c.fetchall()]
        conn.close()

        for user_id in user_ids:
            await self._reveal_for_user(user_id)

        channel_id = self.cfg["capsule_channel_id"]
        channel = self.bot.get_channel(channel_id)
        if channel:
            announce = discord.Embed(
                title="The Time Capsules Have Been Opened",
                description=(
                    f"One year ago, **{len(user_ids)}** members of this server sealed a time capsule.\n\n"
                    "Everything they wrote is below. Check your DMs to read your own entries.\n\n"
                    "Thank you for being part of this community. Here's to another year together."
                ),
                color=EVENT_COLOR,
            )
            announce.set_footer(text="5th Anniversary Event \u00b7 Opened August 16, 2027")
            await channel.send(embed=announce)
            await self._reveal_public(channel, user_ids)

    @daily_capsule_post.before_loop
    async def before_daily_capsule(self):
        await self.bot.wait_until_ready()

    @reveal_capsule.before_loop
    async def before_reveal(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ #
    # Slash commands                                                       #
    # ------------------------------------------------------------------ #

    capsule_group = app_commands.Group(
        name="capsule",
        description="5th Anniversary Time Capsule commands",
    )

    @capsule_group.command(
        name="count",
        description="See how many people have submitted a capsule entry this week",
    )
    async def capsule_count(self, interaction: discord.Interaction):
        self.cfg = _load_config()
        if _event_day(self.cfg) is None:
            await interaction.response.send_message(
                "The Time Capsule event isn't active right now (Aug 16-22, 2026).", ephemeral=True
            )
            return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(DISTINCT user_id) FROM capsule_submissions")
        total = c.fetchone()[0]
        conn.close()

        embed = discord.Embed(
            title="Time Capsule \u2014 Sealed So Far",
            description=(
                f"**{total}** {'person has' if total == 1 else 'people have'} "
                "submitted at least one capsule entry this week.\n\n"
                "Submit yours with `/capsule submit` before August 22!"
            ),
            color=get_embed_color(interaction.user.id),
        )
        embed.set_footer(text="5th Anniversary Event \u00b7 Aug 16\u201322, 2026")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        interaction.client.dispatch("leagues_event", interaction.user.id, "capsule_count", "done", interaction.user)


async def setup(bot: commands.Bot):
    await bot.add_cog(TimeCapsule(bot))
