import json
import sqlite3
import uuid
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
SHOWCASE_DIR    = Path(__file__).parent.parent.parent / "lilacrose.dev" / "bots" / "lacie" / "static" / "uploads" / "showcase"


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
        CREATE TABLE IF NOT EXISTS showcase_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            caption TEXT,
            image_url TEXT NOT NULL,
            message_id INTEGER,
            submitted_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


class Showcase(commands.Cog):
    """Manages the 5th Anniversary art/screenshot showcase."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _init_db()

    def _get_showcase_channel(self) -> discord.TextChannel | None:
        cfg = _load_config()
        name = cfg.get("showcase_channel_name", "art-showcase")
        guild = self.bot.get_guild(GUILD_ID)
        if guild is None:
            return None
        return discord.utils.get(guild.text_channels, name=name)

    @app_commands.command(name="showcase", description="[Event Ended] Submit your art or screenshot to the 5th Anniversary showcase", default_member_permissions=discord.Permissions(administrator=True))
    @app_commands.describe(
        image="The image to submit",
        caption="Optional caption for your submission"
    )
    async def showcase_submit(self, interaction: discord.Interaction, image: discord.Attachment, caption: str = None):
        cfg = _load_config()
        if not _event_active(cfg):
            await interaction.response.send_message(
                "The showcase isn't open right now.", ephemeral=True
            )
            return

        if not image.content_type or not image.content_type.startswith("image/"):
            await interaction.response.send_message(
                "Please attach an image file.", ephemeral=True
            )
            return

        channel = self._get_showcase_channel()
        if channel is None:
            await interaction.response.send_message(
                "Showcase channel not found. Please let staff know!", ephemeral=True
            )
            return

        # Download and save image locally
        local_filename = None
        try:
            SHOWCASE_DIR.mkdir(parents=True, exist_ok=True)
            ext = (image.filename.rsplit(".", 1)[-1].lower() if "." in image.filename else "png")
            local_filename = f"{uuid.uuid4().hex}.{ext}"
            await image.save(SHOWCASE_DIR / local_filename)
        except Exception as e:
            logger.warning(f"Showcase: failed to save image locally: {e}")
            local_filename = None

        # Store in DB
        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO showcase_submissions (user_id, caption, image_url, local_filename, submitted_at) VALUES (?,?,?,?,?)",
            (interaction.user.id, caption, image.url, local_filename, datetime.utcnow().isoformat()),
        )
        submission_id = c.lastrowid
        conn.commit()
        conn.close()

        # Post embed in showcase channel
        embed = discord.Embed(color=0xB48EAD)
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url,
        )
        if caption:
            embed.description = caption
        embed.set_image(url=image.url)
        embed.set_footer(text=f"5th Anniversary Showcase  •  submission #{submission_id}")

        msg = await channel.send(embed=embed)

        # Store message ID for reaction tracking
        conn = sqlite3.connect(LEAGUES_DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE showcase_submissions SET message_id=? WHERE id=?", (msg.id, submission_id))
        conn.commit()
        conn.close()

        # Trigger leagues task check
        self.bot.dispatch("leagues_action", interaction.user.id, "submit_showcase", interaction.user)

        await interaction.response.send_message(
            "Your submission is live on the showcase! Check it out at anniversary.lilacrose.dev/showcase ♡",
            ephemeral=True,
        )
        logger.info(f"Showcase submission: user={interaction.user.id} id={submission_id}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Showcase(bot))
