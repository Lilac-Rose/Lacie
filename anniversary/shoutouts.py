import json
import sqlite3
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, date, timezone
from pathlib import Path
from utils.constants import GUILD_ID
from utils.logger import get_logger

logger = get_logger(__name__)

CONFIG_PATH     = Path(__file__).parent / "config.json"
LEAGUES_DB_PATH = Path(__file__).parent.parent / "data" / "leagues.db"

MAX_LENGTH = 300


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
    end = datetime.fromisoformat(cfg["event_end_date"]).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc,
    )
    return start <= now <= end


def _init_db():
    LEAGUES_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(LEAGUES_DB_PATH)
    c = conn.cursor()
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
        CREATE TABLE IF NOT EXISTS shoutout_bans (
            user_id INTEGER PRIMARY KEY
        )
    """)
    conn.commit()
    conn.close()


def _is_banned(user_id: int) -> bool:
    conn = sqlite3.connect(LEAGUES_DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM shoutout_bans WHERE user_id=?", (user_id,))
    banned = c.fetchone() is not None
    conn.close()
    return banned


class Shoutouts(commands.Cog):
    """Manages the 5th Anniversary shoutout wall."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _init_db()

    def _get_shoutout_channel(self) -> discord.TextChannel | None:
        cfg = _load_config()
        name = cfg.get("shoutout_channel_name", "shoutout-wall")
        guild = self.bot.get_guild(GUILD_ID)
        if guild is None:
            return None
        return discord.utils.get(guild.text_channels, name=name)

    @app_commands.command(name="shoutout", description="[Event Ended] Send a shoutout to a server member for the anniversary wall", default_member_permissions=discord.Permissions(administrator=True))
    @app_commands.describe(
        member="The member you want to shout out",
        message=f"Your message (max {MAX_LENGTH} characters)"
    )
    async def shoutout(self, interaction: discord.Interaction, member: discord.Member, message: str):
        cfg = _load_config()
        if not _event_active(cfg):
            await interaction.response.send_message(
                "The shoutout wall isn't open right now.", ephemeral=True
            )
            return

        if _is_banned(interaction.user.id):
            await interaction.response.send_message(
                "You're not able to send shoutouts.", ephemeral=True
            )
            return

        if member.id == interaction.user.id:
            await interaction.response.send_message(
                "You can't shoutout yourself!", ephemeral=True
            )
            return

        if len(message) > MAX_LENGTH:
            await interaction.response.send_message(
                f"Message too long — keep it under {MAX_LENGTH} characters.", ephemeral=True
            )
            return

        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()
        try:
            c.execute(
                "INSERT INTO shoutout_submissions (from_user_id, to_user_id, message, submitted_at) VALUES (?,?,?,?)",
                (interaction.user.id, member.id, message, datetime.utcnow().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            await interaction.response.send_message(
                f"You've already sent a shoutout to {member.display_name}! You can only send one per person.",
                ephemeral=True,
            )
            return
        conn.close()

        channel = self._get_shoutout_channel()
        if channel:
            embed = discord.Embed(description=message, color=0xB48EAD)
            embed.set_author(
                name=f"{interaction.user.display_name} → {member.display_name}",
                icon_url=interaction.user.display_avatar.url,
            )
            embed.set_footer(text="5th Anniversary Shoutout Wall  •  Aug 16–22, 2026")
            await channel.send(embed=embed)

        self.bot.dispatch("leagues_action", interaction.user.id, "submit_shoutout", interaction.user)
        self.bot.dispatch("leagues_action", member.id, "shoutout_received", member)

        await interaction.response.send_message(
            f"Your shoutout to **{member.display_name}** is live on the wall! Check it out at anniversary.lilacrose.dev/shoutouts ♡",
            ephemeral=True,
        )
        logger.info(f"Shoutout: from={interaction.user.id} to={member.id}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Shoutouts(bot))
