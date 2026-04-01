import json
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from pathlib import Path

from moderation.loader import ModerationBase
from utils.logger import get_logger
from utils.constants import GUILD_ID

logger = get_logger(__name__)

BACKUP_PATH = Path(__file__).parent.parent / "data" / "april_fools_backup.json"

# 12pm EDT (UTC-4) on April 2nd 2026 = 16:00 UTC
REVERT_TIME = datetime(2026, 4, 2, 16, 0, 0, tzinfo=timezone.utc)

# Channel names are assigned in order from these lists; they cycle if needed.
# Channels within the same category will still appear together visually.
JOHN_CHANNELS = [
    "john-central", "the-john", "john-talk", "john-zone", "john-hub",
    "john-pit", "john-lounge", "johns-corner", "john-station", "john-world",
    "john-land", "john-den", "john-cave", "john-nest", "john-lair",
    "john-keep", "john-hall", "john-tower", "john-bay", "john-cove",
    "john-glen", "john-vale", "john-haunt", "john-spot", "johns-domain",
    "john-fort", "john-base", "john-grove", "john-peak", "john-ridge",
]

JOHN_CATEGORIES = [
    "JOHN ZONE", "THE JOHN SECTOR", "JOHN TERRITORY", "JOHN DOMAIN",
    "JOHN LAND", "JOHN CENTRAL", "JOHN SPACE", "JOHN HQ",
    "JOHN DISTRICT", "JOHN PROVINCE",
]

JOHN_ROLES = [
    "John", "Big John", "Baby John", "John Jr.", "True John",
    "John Adjacent", "John Enthusiast", "Honorary John", "John Supreme",
    "John The First", "John-ling", "John's Chosen", "John Master",
    "John Novice", "John Elder", "John Prime", "John Incarnate",
    "Proto-John", "John Acolyte", "John Apostle",
]


class AprilFools(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._revert_task: asyncio.Task | None = None

    async def cog_load(self):
        if BACKUP_PATH.exists():
            logger.info("April Fools: backup found on load, scheduling auto-revert")
            self._schedule_revert()

    def cog_unload(self):
        if self._revert_task and not self._revert_task.done():
            self._revert_task.cancel()

    def _schedule_revert(self):
        if self._revert_task and not self._revert_task.done():
            return
        self._revert_task = asyncio.create_task(self._wait_and_revert())

    async def _wait_and_revert(self):
        now = datetime.now(timezone.utc)
        delay = (REVERT_TIME - now).total_seconds()
        if delay > 0:
            logger.info(f"April Fools: auto-revert in {delay:.0f}s ({REVERT_TIME.isoformat()})")
            await asyncio.sleep(delay)
        await self.bot.wait_until_ready()
        ok, msg = await self._do_revert()
        logger.info(f"April Fools: auto-revert result — {msg}")

    async def _do_johnify(self, guild: discord.Guild) -> tuple[bool, str]:
        if BACKUP_PATH.exists():
            return False, "Already Johnified! Use `/unjohnify` to revert first."

        backup: dict[str, dict[str, str]] = {"channels": {}, "roles": {}}

        ch_idx = 0
        cat_idx = 0
        for channel in guild.channels:
            backup["channels"][str(channel.id)] = channel.name
            try:
                if isinstance(channel, discord.CategoryChannel):
                    new_name = JOHN_CATEGORIES[cat_idx % len(JOHN_CATEGORIES)]
                    cat_idx += 1
                else:
                    new_name = JOHN_CHANNELS[ch_idx % len(JOHN_CHANNELS)]
                    ch_idx += 1
                await channel.edit(name=new_name, reason="April Fools: Johnification")
                await asyncio.sleep(0.6)
            except Exception as e:
                logger.warning(f"April Fools: could not rename channel {channel.id} ({channel.name}): {e}")

        role_idx = 0
        for role in guild.roles:
            if role.is_default() or role.managed:
                continue
            backup["roles"][str(role.id)] = role.name
            try:
                new_name = JOHN_ROLES[role_idx % len(JOHN_ROLES)]
                role_idx += 1
                await role.edit(name=new_name, reason="April Fools: Johnification")
                await asyncio.sleep(0.6)
            except Exception as e:
                logger.warning(f"April Fools: could not rename role {role.id} ({role.name}): {e}")

        BACKUP_PATH.write_text(json.dumps(backup, indent=2))
        logger.info("April Fools: Johnification complete")
        self._schedule_revert()
        return True, "John."

    async def _do_revert(self) -> tuple[bool, str]:
        if not BACKUP_PATH.exists():
            return False, "Nothing to revert — no backup found."

        backup = json.loads(BACKUP_PATH.read_text())
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            logger.error("April Fools: guild not found during revert")
            return False, "Guild not found."

        for ch_id, name in backup.get("channels", {}).items():
            channel = guild.get_channel(int(ch_id))
            if channel:
                try:
                    await channel.edit(name=name, reason="April Fools: De-Johnification")
                    await asyncio.sleep(0.6)
                except Exception as e:
                    logger.warning(f"April Fools: could not restore channel {ch_id}: {e}")

        for role_id, name in backup.get("roles", {}).items():
            role = guild.get_role(int(role_id))
            if role:
                try:
                    await role.edit(name=name, reason="April Fools: De-Johnification")
                    await asyncio.sleep(0.6)
                except Exception as e:
                    logger.warning(f"April Fools: could not restore role {role_id}: {e}")

        BACKUP_PATH.unlink()
        logger.info("April Fools: De-Johnification complete")
        return True, "De-Johnified. The Johns have been reclaimed."

    @app_commands.command(name="johnify", description="Johnify the entire server (April Fools)")
    @ModerationBase.is_admin()
    async def johnify(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ok, msg = await self._do_johnify(interaction.guild)
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="unjohnify", description="Revert the Johnification and restore all names")
    @ModerationBase.is_admin()
    async def unjohnify(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ok, msg = await self._do_revert()
        await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AprilFools(bot))
