# /image/obama.py
import os
import io
import aiohttp
from PIL import Image
import discord
from discord import app_commands
from discord.ext import commands
import numpy as np
import asyncio

class Obamaify(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.obama_path = os.path.join(os.path.dirname(__file__), "..", "media", "obama.jpg")

    async def _fetch_avatar(self, url: str) -> Image.Image:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.read()
        return Image.open(io.BytesIO(data)).convert("RGB")

    def _generate_mosaic(self, avatar_img: Image.Image, obama_img: Image.Image, tile_count: int) -> io.BytesIO:
        obama_img = obama_img.convert("RGB")
        obama_w, obama_h = obama_img.size

        tile_w = obama_w // tile_count
        tile_h = obama_h // tile_count

        avatar_tile = avatar_img.resize((tile_w, tile_h))
        output = Image.new("RGB", (tile_w * tile_count, tile_h * tile_count))
        obama_array = np.array(obama_img)

        for y in range(tile_count):
            for x in range(tile_count):
                tile_array = obama_array[y*tile_h:(y+1)*tile_h, x*tile_w:(x+1)*tile_w]
                avg_color = tile_array.mean(axis=(0,1))
                tile = avatar_tile.copy()
                tile_arr = np.array(tile).astype(np.float32)
                tint_factor = avg_color / (tile_arr.mean(axis=(0,1)) + 1e-6)
                tile_arr = np.clip(tile_arr * tint_factor, 0, 255).astype(np.uint8)
                tile = Image.fromarray(tile_arr)
                output.paste(tile, (x*tile_w, y*tile_h))

        buf = io.BytesIO()
        output.save(buf, format="PNG")
        buf.seek(0)
        return buf

    @app_commands.command(name="obamify", description="Turn your avatar into a tile-based Obama mosaic")
    @app_commands.describe(tile_count="Number of tiles per row/column (default 32), 1-256")
    async def obamify(self, interaction: discord.Interaction, tile_count: int = 32, user: discord.User = None):
        await interaction.response.defer()
        user = user or interaction.user

        if tile_count > 256 or tile_count < 1:
            await interaction.followup.send("Tilecount must be 1-256")
            return

        if not os.path.exists(self.obama_path):
            await interaction.followup.send("Error: obama.jpg not found.")
            return

        try:
            avatar_url = user.display_avatar.url
            avatar_img = await self._fetch_avatar(avatar_url)
            obama_img = Image.open(self.obama_path).convert("RGB")

            # Run image generation in a separate thread
            buf = await asyncio.to_thread(self._generate_mosaic, avatar_img, obama_img, tile_count)

            await interaction.followup.send(file=discord.File(buf, filename="obama_mosaic.png"))

        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

async def setup(bot):
    await bot.add_cog(Obamaify(bot))