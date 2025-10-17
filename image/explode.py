import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageSequence
import io
import asyncio
import aiohttp
import traceback
import os

class Explode(commands.Cog):
    def __init__(self,bot):
        self.bot = bot
        self.session = None
        self.explosion_path = os.path.join(os.path.dirname(__file__),"..", "media","explosion-deltarune.gif")

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    def explode_avatar(self, avatar_bytes: bytes) -> bytes:
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        explosion = Image.open(self.explosion_path)  # ❌ removed .convert("RGBA") here

        avatar_size = avatar.size
        frames = []

        for frame in ImageSequence.Iterator(explosion):
            frame = frame.convert("RGBA")  # ✅ conversion now happens per-frame
            frame_resized = frame.resize(avatar_size, Image.Resampling.LANCZOS)
            combined = Image.new("RGBA", avatar_size)
            combined.paste(avatar, (0, 0))
            combined.paste(frame_resized, (0, 0), frame_resized)
            frames.append(combined)

        out = io.BytesIO()
        frames[0].save(
            out,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=explosion.info.get("duration", 50),
            loop=0,
            disposal=2
        )
        out.seek(0)
        return out.getvalue()

    
    @app_commands.command(name="explode", description="Make a user's avatar explode.")
    @app_commands.describe(
        user="The user whose avatar to explide (defaults to you)"
    )
    async def explode(self, interaction: discord.Interaction, user: discord.User = None):
        user = user or interaction.user
        try:
            await interaction.response.defer(thinking=True)

            avatar_url = user.display_avatar.with_format("png").with_size(256)

            if not self.session or self.session.closed:
                self.session = aiohttp.ClientSession()

            async with self.session.get(str(avatar_url)) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status} while fetching avatar")
                avatar_bytes = await resp.read()

            exploded_bytes = await asyncio.to_thread(self.explode_avatar, avatar_bytes)

            file = discord.File(io.BytesIO(exploded_bytes), filename="exploded.gif")
            await interaction.followup.send(f"{user.display_name} just got exploded!", file=file)

        except Exception as e:
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An error occured while processing the explosion.", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "An error occurred while processing the explosion.", ephemeral=True
                )

async def setup(bot: commands.Bot):
    await bot.add_cog(Explode(bot))