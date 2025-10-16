import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image
import io
import asyncio
import aiohttp
import traceback

class Bitcrush(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = None

    async def cog_load(self):
        print("[bitcrush] Cog loading: creating aiohttp session")
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        print("[bitcrush] Cog unloading: closing aiohttp session")
        if self.session:
            await self.session.close()

    def bitcrush_image(self, image_bytes: bytes, bits: int) -> bytes:
        print("[bitcrush] Starting image quantization thread")
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        colors = 2 ** bits
        crushed = img.quantize(colors=colors, method=Image.MEDIANCUT)
        out = io.BytesIO()
        crushed.save(out, format="PNG")
        out.seek(0)
        print("[bitcrush] Image quantization complete")
        return out.getvalue()

    @app_commands.command(name="bitcrush", description="Bitcrush a user's avatar to a lower bits-per-pixel value.")
    @app_commands.describe(
        user="The user whose avatar to bitcrush (defaults to you)",
        bpp="Bits per pixel (1–23, default 8)"
    )
    async def bitcrush(self, interaction: discord.Interaction, bpp: int = 8, user: discord.User = None):
        print("[bitcrush] Command invoked")
        user = user or interaction.user
        print(f"[bitcrush] user={user}, bpp={bpp}")

        if bpp < 1 or bpp > 23:
            print("[bitcrush] Invalid bpp value")
            await interaction.response.send_message("Please choose a bit depth between 1 and 23.", ephemeral=True)
            return

        try:
            print("[bitcrush] Deferring interaction...")
            await interaction.response.defer(thinking=True)
            print("[bitcrush] Deferred successfully")

            avatar_url = user.display_avatar.with_format("png").with_size(512)
            print(f"[bitcrush] Avatar URL: {avatar_url}")

            # Ensure session exists
            if not self.session or self.session.closed:
                print("[bitcrush] Session missing or closed, recreating")
                self.session = aiohttp.ClientSession()

            async with self.session.get(str(avatar_url)) as resp:
                print(f"[bitcrush] HTTP status: {resp.status}")
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status} while fetching avatar")
                image_bytes = await resp.read()
            print("[bitcrush] Image downloaded successfully")

            crushed_bytes = await asyncio.to_thread(self.bitcrush_image, image_bytes, bpp)
            print("[bitcrush] Image processed successfully")

            file = discord.File(io.BytesIO(crushed_bytes), filename=f"bitcrushed_{bpp}bit.png")

            await interaction.followup.send(
                f"{user.display_name}'s avatar, bitcrushed to {bpp} bits:",
                file=file
            )
            print("[bitcrush] File sent successfully")

        except Exception as e:
            print(f"[bitcrush] ERROR: {e}")
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("An error occurred while processing the image.", ephemeral=True)
            else:
                await interaction.followup.send("An error occurred while processing the image.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Bitcrush(bot))
    print("[bitcrush] Cog setup complete")
