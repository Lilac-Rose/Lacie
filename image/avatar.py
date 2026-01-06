import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageOps, ImageSequence
import io
import asyncio
import aiohttp
import traceback
import os
import numpy as np
from scipy.ndimage import uniform_filter

class AvatarCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = None
        self.explosion_path = os.path.join(os.path.dirname(__file__), "..", "media", "explosion-deltarune.gif")
        self.obama_path = os.path.join(os.path.dirname(__file__), "..", "media", "obama.jpg")
    
    async def cog_load(self):
        self.session = aiohttp.ClientSession()
    
    async def cog_unload(self):
        if self.session:
            await self.session.close()
    
    def get_avatar_url(self, user, avatar_type_choice):
        """Returns a valid avatar object (never None)."""
        use_global = avatar_type_choice and avatar_type_choice.value == "global"

        # always safe
        if isinstance(user, discord.Member) and not use_global and user.guild_avatar:
            return user.guild_avatar
        else:
            return user.display_avatar

    # Create the main avatar command group
    avatar_group = app_commands.Group(name="avatar", description="Avatar manipulation commands")

    # ----------------------------------------------------------------------
    # /avatar show
    # ----------------------------------------------------------------------
    @avatar_group.command(name="show", description="Show your avatar or another user's avatar")
    @app_commands.describe(
        user="The user whose avatar to show (defaults to you)",
        avatar_type="Choose between server or global avatar"
    )
    @app_commands.choices(
        avatar_type=[
            app_commands.Choice(name="Server Avatar", value="server"),
            app_commands.Choice(name="Global Avatar", value="global")
        ]
    )
    async def avatar_show(self, interaction: discord.Interaction, user: discord.User = None, avatar_type: app_commands.Choice[str] = None):
        await interaction.response.defer(thinking=True)

        target = user or interaction.user
        avatar = self.get_avatar_url(target, avatar_type)
        avatar_url = avatar.url

        embed_color = discord.Color.blue()
        if self.bot.get_cog("EmbedColor"):
            embed_color = self.bot.get_cog("EmbedColor").get_user_color(interaction.user)
        
        embed = discord.Embed(
            title=f"{target.display_name}'s Avatar",
            color=embed_color
        )
        embed.set_image(url=avatar_url)
        embed.add_field(name="Direct Link", value=f"[Open Avatar]({avatar_url})")

        await interaction.followup.send(embed=embed)

    # ----------------------------------------------------------------------
    # /avatar bitcrush
    # ----------------------------------------------------------------------
    @avatar_group.command(name="bitcrush", description="Bitcrush a user's avatar to a lower bits-per-pixel value")
    @app_commands.describe(
        user="The user whose avatar to bitcrush (defaults to you)",
        bpp="Bits per pixel (1–8, default 8)",
        avatar_type="Choose between server or global avatar"
    )
    @app_commands.choices(
        avatar_type=[
            app_commands.Choice(name="Server Avatar", value="server"),
            app_commands.Choice(name="Global Avatar", value="global")
        ]
    )
    async def avatar_bitcrush(self, interaction: discord.Interaction, bpp: int = 8, user: discord.User = None, avatar_type: app_commands.Choice[str] = None):
        await interaction.response.defer(thinking=True)

        user = user or interaction.user
        
        if bpp < 1 or bpp > 8:
            await interaction.followup.send("Please choose a bit depth between 1 and 8.", ephemeral=True)
            return
        
        try:
            avatar = self.get_avatar_url(user, avatar_type)
            avatar_url = avatar.with_format("png").with_size(512)
            
            if not self.session or self.session.closed:
                self.session = aiohttp.ClientSession()
            
            async with self.session.get(str(avatar_url)) as resp:
                resp.raise_for_status()
                image_bytes = await resp.read()
            
            crushed_bytes = await asyncio.to_thread(self._bitcrush_image, image_bytes, bpp)
            file = discord.File(io.BytesIO(crushed_bytes), filename=f"bitcrushed_{bpp}bit.png")
            
            await interaction.followup.send(
                f"{user.display_name}'s avatar, bitcrushed to {bpp} bit(s):",
                file=file
            )
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("An error occurred while processing the image.", ephemeral=True)
    
    def _bitcrush_image(self, image_bytes: bytes, bits: int) -> bytes:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        colors = 2 ** bits
        crushed = img.quantize(colors=colors, method=Image.MEDIANCUT)
        out = io.BytesIO()
        crushed.save(out, format="PNG")
        out.seek(0)
        return out.getvalue()

    # ----------------------------------------------------------------------
    # /avatar explode
    # ----------------------------------------------------------------------
    @avatar_group.command(name="explode", description="Make a user's avatar explode")
    @app_commands.describe(
        user="The user whose avatar to explode (defaults to you)",
        avatar_type="Choose between server or global avatar"
    )
    @app_commands.choices(
        avatar_type=[
            app_commands.Choice(name="Server Avatar", value="server"),
            app_commands.Choice(name="Global Avatar", value="global")
        ]
    )
    async def avatar_explode(self, interaction: discord.Interaction, user: discord.User = None, avatar_type: app_commands.Choice[str] = None):
        await interaction.response.defer(thinking=True)

        user = user or interaction.user
        
        try:
            avatar = self.get_avatar_url(user, avatar_type)
            avatar_url = avatar.with_format("png").with_size(256)
            
            if not self.session or self.session.closed:
                self.session = aiohttp.ClientSession()
            
            async with self.session.get(str(avatar_url)) as resp:
                resp.raise_for_status()
                avatar_bytes = await resp.read()
            
            exploded_bytes = await asyncio.to_thread(self._explode_avatar, avatar_bytes)
            file = discord.File(io.BytesIO(exploded_bytes), filename="exploded.gif")
            
            await interaction.followup.send(f"{user.display_name} just got exploded!", file=file)
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("An error occurred while processing the explosion.", ephemeral=True)
    
    def _explode_avatar(self, avatar_bytes: bytes) -> bytes:
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        explosion = Image.open(self.explosion_path)
        avatar_size = avatar.size
        frames = []
        
        for frame in ImageSequence.Iterator(explosion):
            frame = frame.convert("RGBA")
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

    # ----------------------------------------------------------------------
    # /avatar grayscale
    # ----------------------------------------------------------------------
    @avatar_group.command(name="grayscale", description="Grayscale a user's avatar")
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
    async def avatar_grayscale(self, interaction: discord.Interaction, user: discord.User = None, avatar_type: app_commands.Choice[str] = None):
        await interaction.response.defer(thinking=True)

        user = user or interaction.user
        
        try:
            avatar = self.get_avatar_url(user, avatar_type)
            avatar_url = avatar.with_format("png").with_size(512)
            
            async with self.session.get(str(avatar_url)) as resp:
                resp.raise_for_status()
                image_bytes = await resp.read()
            
            grayscaled_bytes = await asyncio.to_thread(self._grayscale_image, image_bytes)
            file = discord.File(io.BytesIO(grayscaled_bytes), filename="grayscaled.png")
            
            await interaction.followup.send(
                f"{user.display_name}'s avatar, grayscaled:",
                file=file
            )
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("An error occurred while processing the image.", ephemeral=True)
    
    def _grayscale_image(self, image_bytes: bytes) -> bytes:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        grayscaled = ImageOps.grayscale(img)
        out = io.BytesIO()
        grayscaled.save(out, format="PNG")
        out.seek(0)
        return out.getvalue()

    # ----------------------------------------------------------------------
    # /avatar inverse
    # ----------------------------------------------------------------------
    @avatar_group.command(name="inverse", description="Invert the colors of a user's avatar")
    @app_commands.describe(
        user="The user whose avatar to invert (defaults to you)",
        avatar_type="Choose between server or global avatar"
    )
    @app_commands.choices(
        avatar_type=[
            app_commands.Choice(name="Server Avatar", value="server"),
            app_commands.Choice(name="Global Avatar", value="global")
        ]
    )
    async def avatar_inverse(self, interaction: discord.Interaction, user: discord.User = None, avatar_type: app_commands.Choice[str] = None):
        await interaction.response.defer(thinking=True)

        user = user or interaction.user
        
        try:
            avatar = self.get_avatar_url(user, avatar_type)
            avatar_url = avatar.with_format("png").with_size(512)
            
            async with self.session.get(str(avatar_url)) as resp:
                resp.raise_for_status()
                image_bytes = await resp.read()
            
            inverted_bytes = await asyncio.to_thread(self._invert_image, image_bytes)
            file = discord.File(io.BytesIO(inverted_bytes), filename="inverted.png")
            
            await interaction.followup.send(
                f"{user.display_name}'s avatar, color-inverted:",
                file=file
            )
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("An error occurred while processing the image.", ephemeral=True)
    
    def _invert_image(self, image_bytes: bytes) -> bytes:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        inverted = ImageOps.invert(img)
        out = io.BytesIO()
        inverted.save(out, format="PNG")
        out.seek(0)
        return out.getvalue()

    # ----------------------------------------------------------------------
    # /avatar kuwahara
    # ----------------------------------------------------------------------
    @avatar_group.command(name="kuwahara", description="Apply a Kuwahara filter to a user's avatar for a painterly effect")
    @app_commands.describe(
        user="The user whose avatar to filter (defaults to you)",
        kernel_size="Filter kernel size (3-15, odd numbers only, default 5)",
        avatar_type="Choose between server or global avatar"
    )
    @app_commands.choices(
        avatar_type=[
            app_commands.Choice(name="Server Avatar", value="server"),
            app_commands.Choice(name="Global Avatar", value="global")
        ]
    )
    async def avatar_kuwahara(self, interaction: discord.Interaction, kernel_size: int = 5, user: discord.User = None, avatar_type: app_commands.Choice[str] = None):
        await interaction.response.defer(thinking=True)

        user = user or interaction.user
        
        if kernel_size < 3 or kernel_size > 15 or kernel_size % 2 == 0:
            await interaction.followup.send("Kernel size must be an odd number between 3 and 15.", ephemeral=True)
            return
        
        try:
            avatar = self.get_avatar_url(user, avatar_type)
            avatar_url = avatar.with_format("png").with_size(512)
            
            if not self.session or self.session.closed:
                self.session = aiohttp.ClientSession()
            
            async with self.session.get(str(avatar_url)) as resp:
                resp.raise_for_status()
                image_bytes = await resp.read()
            
            filtered_bytes = await asyncio.to_thread(self._kuwahara_filter, image_bytes, kernel_size)
            file = discord.File(io.BytesIO(filtered_bytes), filename="kuwahara.png")
            
            await interaction.followup.send(
                f"{user.display_name}'s avatar with Kuwahara filter (kernel size {kernel_size}):",
                file=file
            )
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("An error occurred while processing the image.", ephemeral=True)
    
    def _kuwahara_filter(self, image_bytes: bytes, kernel_size: int) -> bytes:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(img, dtype=np.float32)
        
        h, w, c = img_array.shape
        result = np.zeros_like(img_array)
        
        radius = kernel_size // 2
        
        # Process each color channel separately
        for ch in range(c):
            channel = img_array[:, :, ch]
            
            # Calculate mean and variance for the four quadrants
            mean = uniform_filter(channel, kernel_size, mode='reflect')
            mean_sq = uniform_filter(channel**2, kernel_size, mode='reflect')
            variance = mean_sq - mean**2
            
            # Create four quadrants by shifting the variance map
            padded_var = np.pad(variance, radius, mode='reflect')
            padded_mean = np.pad(mean, radius, mode='reflect')
            
            # Extract four overlapping regions (quadrants)
            vars = []
            means = []
            for dy in [0, radius]:
                for dx in [0, radius]:
                    vars.append(padded_var[dy:dy+h, dx:dx+w])
                    means.append(padded_mean[dy:dy+h, dx:dx+w])
            
            # Stack and find minimum variance quadrant
            vars_stack = np.stack(vars, axis=0)
            means_stack = np.stack(means, axis=0)
            
            min_var_idx = np.argmin(vars_stack, axis=0)
            
            # Select mean from quadrant with minimum variance
            for i in range(4):
                mask = (min_var_idx == i)
                result[:, :, ch][mask] = means_stack[i][mask]
        
        result = np.clip(result, 0, 255).astype(np.uint8)
        filtered_img = Image.fromarray(result)
        
        out = io.BytesIO()
        filtered_img.save(out, format="PNG")
        out.seek(0)
        return out.getvalue()

    # ----------------------------------------------------------------------
    # /avatar obamify
    # ----------------------------------------------------------------------
    @avatar_group.command(name="obamify", description="Turn a user's avatar into a tile-based Obama mosaic")
    @app_commands.describe(
        user="The user whose avatar to obamify (defaults to you)",
        tile_count="Number of tiles per row/column (default 32), 1-256",
        avatar_type="Choose between server or global avatar"
    )
    @app_commands.choices(
        avatar_type=[
            app_commands.Choice(name="Server Avatar", value="server"),
            app_commands.Choice(name="Global Avatar", value="global")
        ]
    )
    async def avatar_obamify(self, interaction: discord.Interaction, tile_count: int = 32, user: discord.User = None, avatar_type: app_commands.Choice[str] = None):
        await interaction.response.defer(thinking=True)

        user = user or interaction.user
        
        if tile_count < 1 or tile_count > 256:
            await interaction.followup.send("Tile count must be 1–256.", ephemeral=True)
            return
        
        if not os.path.exists(self.obama_path):
            await interaction.followup.send("Error: obama.jpg not found.", ephemeral=True)
            return
        
        try:
            avatar = self.get_avatar_url(user, avatar_type)
            avatar_url = avatar.url
            
            avatar_img = await self._fetch_avatar(avatar_url)
            obama_img = Image.open(self.obama_path).convert("RGB")
            
            buf = await asyncio.to_thread(self._generate_mosaic, avatar_img, obama_img, tile_count)
            
            await interaction.followup.send(file=discord.File(buf, filename="obama_mosaic.png"))
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("An error occurred during mosaic generation.", ephemeral=True)
    
    async def _fetch_avatar(self, url: str) -> Image.Image:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
        
        async with self.session.get(url) as resp:
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

async def setup(bot):
    await bot.add_cog(AvatarCommands(bot))