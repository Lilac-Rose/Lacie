import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageOps
import io
import asyncio
import aiohttp
import traceback

class Inverse(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    def invert_image(self, image_bytes: bytes) -> bytes:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        inverted = ImageOps.invert(img)
        out = io.BytesIO()
        inverted.save(out, format="PNG")
        out.seek(0)
        return out.getvalue()

    @app_commands.command(name="inverse", description="Invert the colors of a user's avatar.")
    @app_commands.describe(
        user="The user whose avatar to invert (defaults to you)"
    )
    async def inverse(self, interaction: discord.Interaction, user: discord.User = None):
        user = user or interaction.user

        try:
            await interaction.response.defer(thinking=True)

            avatar_url = user.display_avatar.with_format("png").with_size(512)

            # Ensure session exists
            if not self.session or self.session.closed:
                self.session = aiohttp.ClientSession()

            async with self.session.get(str(avatar_url)) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status} while fetching avatar")
                image_bytes = await resp.read()

            inverted_bytes = await asyncio.to_thread(self.invert_image, image_bytes)

            file = discord.File(io.BytesIO(inverted_bytes), filename="inverted.png")

            await interaction.followup.send(
                f"{user.display_name}'s avatar, color-inverted:",
                file=file
            )

        except Exception as e:
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("An error occurred while processing the image.", ephemeral=True)
            else:
                await interaction.followup.send("An error occurred while processing the image.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Inverse(bot))