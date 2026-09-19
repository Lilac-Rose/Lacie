import json
import discord
from discord.ext import commands, tasks
from pathlib import Path
from utils.logger import get_logger
from utils.constants import GUILD_ID

logger = get_logger(__name__)
CONFIG_PATH = Path(__file__).parent / "config.json"


def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


CHANNEL_NAMES = ["art-showcase", "shoutout-wall"]


class AnniversarySetup(commands.Cog):
    """Creates and maintains the 5th Anniversary category channels on startup."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self._setup_task.start()

    async def cog_unload(self):
        self._setup_task.cancel()

    @tasks.loop(count=1)
    async def _setup_task(self):
        await self.bot.wait_until_ready()
        await self._ensure_channels()

    async def _ensure_channels(self):
        cfg = _load_config()
        category_name = cfg.get("anniversary_category_name", "5th Anniversary")
        guild = self.bot.get_guild(GUILD_ID)
        if guild is None:
            logger.warning("AnniversarySetup: guild not found")
            return

        category = discord.utils.get(guild.categories, name=category_name)
        if category is None:
            logger.warning(f"AnniversarySetup: category '{category_name}' not found — create it manually")
            return

        for name in CHANNEL_NAMES:
            matches = [ch for ch in guild.channels if ch.name == name]
            if len(matches) > 1:
                # Keep the one inside the category, delete the rest
                in_cat = [ch for ch in matches if ch.category_id == category.id]
                keep = in_cat[0] if in_cat else matches[0]
                for ch in matches:
                    if ch.id != keep.id:
                        try:
                            await ch.delete(reason="AnniversarySetup: removed duplicate channel")
                            logger.info(f"AnniversarySetup: deleted duplicate #{name} ({ch.id})")
                        except Exception as e:
                            logger.error(f"AnniversarySetup: failed to delete duplicate #{name}: {e}")
            elif not matches:
                try:
                    await guild.create_text_channel(name, category=category)
                    logger.info(f"AnniversarySetup: created #{name}")
                except discord.Forbidden:
                    logger.error(f"AnniversarySetup: no permission to create #{name}")
                except Exception as e:
                    logger.error(f"AnniversarySetup: failed to create #{name}: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(AnniversarySetup(bot))
