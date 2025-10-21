import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageOps
import io
import asyncio
import aiohttp
import traceback

class Grayscale(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    def grayscale_image(self, image_bytes: bytes) -> bytes:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        grayscaled = ImageOps.grayscale(img)
        out = io.BytesIO()
        grayscaled.save(out, format="PNG")
        out.seek(0)
        return out.getvalue()

    @app_commands.command(name="grayscale", description="Grayscales the colors of a user's avatar.")
    @app_commands.describe(
        user="The user whose avatar to grayscale (defaults to you)",
        avatar_type="Choose between server or global avatar"
    )
    @app_commands.choices(
        avatar_type=[
            app_commands.Choice(name="Server Avatar", value="server"),
            app_commands.Choice(name="Global Avatar", value="global")
        ]
    )
    async def grayscale(self, interaction: discord.Interaction, user: discord.User = None, avatar_type: app_commands.Choice[str] = None):
        user = user or interaction.user

        try:
            await interaction.response.defer(thinking=True)
            
            # Determine which avatar to use
            use_global = avatar_type and avatar_type.value == "global"
            if isinstance(user, discord.Member) and not use_global and user.avatar:
                avatar_url = user.display_avatar.with_format("png").with_size(512)
            else:
                avatar_url = user.avatar.with_format("png").with_size(512) if user.avatar else user.default_avatar.with_format("png").with_size(512)
            
            # Ensure session exists
            if not self.session or self.session.closed:
                self.session = aiohttp.ClientSession()

            async with self.session.get(str(avatar_url)) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status} while fetching avatar")
                image_bytes = await resp.read()

            grayscaled_bytes = await asyncio.to_thread(self.grayscale_image, image_bytes)
            file = discord.File(io.BytesIO(grayscaled_bytes), filename="grayscaled.png")

            await interaction.followup.send(
                f"{user.display_name}'s avatar, grayscaled:",
                file=file
            )

        except Exception as e:
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("An error occurred while processing the image.", ephemeral=True)
            else:
                await interaction.followup.send("An error occurred while processing the image.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Grayscale(bot))