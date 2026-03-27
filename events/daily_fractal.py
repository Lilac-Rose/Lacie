import io
import aiohttp
import discord
from discord.ext import commands, tasks
from datetime import datetime, time, timezone
from utils.logger import get_logger

logger = get_logger(__name__)

FRACTAL_CHANNEL_ID = 876772600704020533
WEBSITE_BASE = "http://localhost:3000"
OWNER_ID = 252130669919076352

PALETTE_NAMES = [
    "Fire", "Ocean", "Forest", "Sunset", "Purple Dream",
    "Toxic", "Ice", "Copper", "Neon Pink", "Volcanic",
    "Electric Blue", "Autumn", "Candy", "Matrix", "Deep Sea",
    "Crimson", "Gold Rush", "Midnight", "Lava", "Rainbow",
]

DAILY_POST_TIME = time(hour=12, minute=0, tzinfo=timezone.utc)


class DailyFractal(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.daily_fractal.start()

    def cog_unload(self):
        self.daily_fractal.cancel()

    async def _post_fractal(self):
        channel = self.bot.get_channel(FRACTAL_CHANNEL_ID)
        if channel is None:
            logger.error("Daily fractal: channel not found")
            return

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{WEBSITE_BASE}/fractal/api/today") as resp:
                    if resp.status != 200:
                        logger.error(f"Daily fractal: API returned {resp.status}")
                        return
                    data = await resp.json()

                meta = data.get("metadata", {})

                async with session.get(f"{WEBSITE_BASE}/fractal/api/image/{today}") as img_resp:
                    if img_resp.status != 200:
                        logger.error(f"Daily fractal: image fetch returned {img_resp.status}")
                        return
                    image_bytes = await img_resp.read()

        except Exception as e:
            logger.error(f"Daily fractal: failed to fetch fractal: {e}")
            return

        fractal_name = meta.get("name", "Unknown")
        fractal_type = meta.get("type", "unknown").replace("_", " ").title()
        seed = meta.get("seed")
        palette = meta.get("palette") or (PALETTE_NAMES[seed % len(PALETTE_NAMES)] if seed is not None else "Unknown")

        embed = discord.Embed(
            title=f"Fractal of the Day — {today}",
            description=f"**{fractal_name}**",
            color=0xB266FF,
        )
        embed.add_field(name="Type", value=fractal_type, inline=True)
        embed.add_field(name="Palette", value=palette, inline=True)
        embed.add_field(name="Seed", value=str(seed) if seed is not None else "Unknown", inline=True)
        embed.set_image(url="attachment://fractal.png")
        embed.set_footer(text="lilacrose.dev/fractal")

        file = discord.File(io.BytesIO(image_bytes), filename="fractal.png")
        await channel.send(embed=embed, file=file)
        logger.info(f"Daily fractal posted for {today}: {fractal_name}")

    @tasks.loop(time=DAILY_POST_TIME)
    async def daily_fractal(self):
        await self._post_fractal()

    @commands.command(name="fractal")
    async def fractal_command(self, ctx):
        if ctx.author.id != OWNER_ID:
            return
        await ctx.message.delete()
        await self._post_fractal()

    @daily_fractal.before_loop
    async def before_daily_fractal(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(DailyFractal(bot))
