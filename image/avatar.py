import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageOps, ImageSequence
import io
from embed.embed_color import get_embed_color
import asyncio
import aiohttp
import os
import tempfile
from pathlib import Path
import numpy as np
from scipy.ndimage import uniform_filter
import cv2
import imageio_ffmpeg
from utils.logger import get_logger

logger = get_logger(__name__)

def _composite_frame(dark, changed, dual, frame_h, frame_w, t1_rgb, t1_alpha, t2_rgb, t2_alpha):
    if dual:
        output = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)
        show1 = dark & changed & (t1_alpha > 0)
        show2 = ~dark & changed & (t2_alpha > 0)
        output[show1] = t1_rgb[show1]
        output[show2] = t2_rgb[show2]
    else:
        output = np.zeros((frame_h, frame_w, 4), dtype=np.uint8)
        show1 = dark & changed & (t1_alpha > 0)
        output[show1, :3] = t1_rgb[show1]
        output[show1, 3] = t1_alpha[show1]
    return output.tobytes()

class AvatarCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = None
        self.explosion_path = Path(__file__).parent.parent / "media" / "explosion-deltarune.gif"
        self.obama_path = Path(__file__).parent.parent / "media" / "obama.jpg"
        self.bad_apple_path = Path(__file__).parent.parent / "media" / "bad-apple"
        self.bad_apple_audio_path = Path(__file__).parent.parent / "media" / "bad_apple.mp3"
        self._bad_apple_frames: list[Path] = []
    
    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        if self.bad_apple_path.exists():
            self._bad_apple_frames = sorted(self.bad_apple_path.glob("*.jpg"))
    
    async def cog_unload(self):
        if self.session:
            await self.session.close()
    
    def get_avatar_url(self, user, avatar_type_choice):
        """Returns a valid avatar object (never None)."""
        use_global = avatar_type_choice and avatar_type_choice.value == "global"

        if use_global:
            # user.avatar is always the global avatar; fall back for default-avatar accounts
            return user.avatar or user.display_avatar
        if isinstance(user, discord.Member) and user.guild_avatar:
            return user.guild_avatar
        return user.display_avatar

    avatar_group = app_commands.Group(name="avatar", description="Avatar manipulation commands")

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

        embed = discord.Embed(
            title=f"{target.display_name}'s Avatar",
            color=get_embed_color(interaction.user.id)
        )
        embed.set_image(url=avatar_url)
        embed.add_field(name="Direct Link", value=f"[Open Avatar]({avatar_url})")

        await interaction.followup.send(embed=embed)

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
            logger.exception("Error in avatar bitcrush")
            await interaction.followup.send("An error occurred while processing the image.", ephemeral=True)

    def _bitcrush_image(self, image_bytes: bytes, bits: int) -> bytes:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        colors = 2 ** bits
        crushed = img.quantize(colors=colors, method=Image.MEDIANCUT)
        out = io.BytesIO()
        crushed.save(out, format="PNG")
        out.seek(0)
        return out.getvalue()

    @avatar_group.command(name="canny_edge", description="Apply Canny edge detection to a user's avatar")
    @app_commands.describe(
        user="The user whose avatar to process (defaults to you)",
        threshold1="Lower threshold for edge detection (default 100)",
        threshold2="Upper threshold for edge detection (default 200)",
        avatar_type="Choose between server or global avatar"
    )
    @app_commands.choices(
        avatar_type=[
            app_commands.Choice(name="Server Avatar", value="server"),
            app_commands.Choice(name="Global Avatar", value="global")
        ]
    )
    async def avatar_canny_edge(self, interaction: discord.Interaction, threshold1: int = 100, threshold2: int = 200, user: discord.User = None, avatar_type: app_commands.Choice[str] = None):
        await interaction.response.defer(thinking=True)

        user = user or interaction.user
        
        if threshold1 < 0 or threshold1 > 500:
            await interaction.followup.send("threshold1 must be between 0 and 500.", ephemeral=True)
            return
        
        if threshold2 < 0 or threshold2 > 500:
            await interaction.followup.send("threshold2 must be between 0 and 500.", ephemeral=True)
            return
        
        if threshold1 >= threshold2:
            await interaction.followup.send("threshold1 must be less than threshold2.", ephemeral=True)
            return
        
        try:
            avatar = self.get_avatar_url(user, avatar_type)
            avatar_url = avatar.with_format("png").with_size(512)
            
            if not self.session or self.session.closed:
                self.session = aiohttp.ClientSession()
            
            async with self.session.get(str(avatar_url)) as resp:
                resp.raise_for_status()
                image_bytes = await resp.read()
            
            edge_bytes = await asyncio.to_thread(self._canny_edge_detection, image_bytes, threshold1, threshold2)
            file = discord.File(io.BytesIO(edge_bytes), filename="canny_edges.png")
            
            await interaction.followup.send(
                f"{user.display_name}'s avatar with Canny edge detection:",
                file=file
            )
        except Exception:
            logger.exception("Error in avatar canny_edge")
            await interaction.followup.send("An error occurred while processing the image.", ephemeral=True)

    def _canny_edge_detection(self, image_bytes: bytes, threshold1: int, threshold2: int) -> bytes:
        # Load image and convert to grayscale
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(img)
        
        # Convert RGB to BGR for OpenCV
        img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
        
        # Convert to grayscale
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        
        # Apply Canny edge detection
        edges = cv2.Canny(gray, threshold1, threshold2)
        
        # Convert back to PIL Image
        edges_img = Image.fromarray(edges)
        
        out = io.BytesIO()
        edges_img.save(out, format="PNG")
        out.seek(0)
        return out.getvalue()

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
            logger.exception("Error in avatar explode")
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
            logger.exception("Error in avatar grayscale")
            await interaction.followup.send("An error occurred while processing the image.", ephemeral=True)

    def _grayscale_image(self, image_bytes: bytes) -> bytes:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        grayscaled = ImageOps.grayscale(img)
        out = io.BytesIO()
        grayscaled.save(out, format="PNG")
        out.seek(0)
        return out.getvalue()

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
            logger.exception("Error in avatar inverse")
            await interaction.followup.send("An error occurred while processing the image.", ephemeral=True)

    def _invert_image(self, image_bytes: bytes) -> bytes:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        inverted = ImageOps.invert(img)
        out = io.BytesIO()
        inverted.save(out, format="PNG")
        out.seek(0)
        return out.getvalue()

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
            logger.exception("Error in avatar kuwahara")
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
            logger.exception("Error in avatar obamify")
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

    @avatar_group.command(name="bad_apple", description="Play Bad Apple with avatar(s) tiled as the fill")
    @app_commands.describe(
        user="User for the black silhouette (defaults to you)",
        user2="User for the white background (omit for transparent background)",
        tile_count="Number of avatar tiles per row (default 16, range 1–64)",
        delta_only="Only show pixels that changed from the previous frame",
        avatar_type="Choose between server or global avatar"
    )
    @app_commands.choices(
        avatar_type=[
            app_commands.Choice(name="Server Avatar", value="server"),
            app_commands.Choice(name="Global Avatar", value="global")
        ]
    )
    async def avatar_bad_apple(self, interaction: discord.Interaction, user: discord.User = None, user2: discord.User = None, tile_count: int = 16, delta_only: bool = False, avatar_type: app_commands.Choice[str] = None):
        await interaction.response.defer(thinking=True)

        user = user or interaction.user

        if tile_count < 1 or tile_count > 64:
            await interaction.followup.send("Tile count must be 1–64.", ephemeral=True)
            return

        if not self.bad_apple_path.exists():
            await interaction.followup.send("Error: Bad Apple frames not found.", ephemeral=True)
            return

        try:
            if not self.session or self.session.closed:
                self.session = aiohttp.ClientSession()

            avatar = self.get_avatar_url(user, avatar_type)
            async with self.session.get(str(avatar.with_format("png").with_size(512))) as resp:
                resp.raise_for_status()
                avatar_bytes = await resp.read()

            avatar2_bytes = None
            if user2 is not None:
                avatar2 = self.get_avatar_url(user2, avatar_type)
                async with self.session.get(str(avatar2.with_format("png").with_size(512))) as resp:
                    resp.raise_for_status()
                    avatar2_bytes = await resp.read()

            tmp_raw = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
            tmp_raw.close()
            raw_path = tmp_raw.name

            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            audio_offset = await self._detect_audio_offset(ffmpeg_exe)
            frame_skip = int(audio_offset * 30)

            frame_w, frame_h, has_alpha = await asyncio.to_thread(
                self._process_bad_apple_frames, avatar_bytes, tile_count, raw_path, avatar2_bytes, frame_skip, delta_only
            )

            buf = await self._encode_bad_apple_video(raw_path, frame_w, frame_h, has_alpha, ffmpeg_exe, audio_offset)

            label = f"{user.display_name} vs {user2.display_name}" if user2 else user.display_name
            ext = "webm" if has_alpha else "mp4"
            await interaction.followup.send(
                f"Bad Apple, but it's {label}:",
                file=discord.File(buf, filename=f"bad_apple.{ext}")
            )
        except Exception:
            logger.exception("Error in avatar bad_apple")
            await interaction.followup.send("An error occurred while generating the video.", ephemeral=True)

    def _build_tiled(self, avatar_bytes: bytes, frame_w: int, frame_h: int, tile_count: int) -> np.ndarray:
        """Build a tiled RGBA canvas of the avatar at frame resolution."""
        img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        tile_w = frame_w // tile_count
        tile_h = tile_w
        tile_arr = np.array(img.resize((tile_w, tile_h), Image.Resampling.LANCZOS))
        tiles_x = -(-frame_w // tile_w)  # ceiling division
        tiles_y = -(-frame_h // tile_h)
        return np.tile(tile_arr, (tiles_y, tiles_x, 1))[:frame_h, :frame_w]

    def _process_bad_apple_frames(self, avatar_bytes: bytes, tile_count: int, raw_path: str, avatar2_bytes: bytes | None = None, frame_skip: int = 0, delta_only: bool = False) -> tuple[int, int, bool]:
        """Process frames and write raw video data to raw_path. Returns (frame_w, frame_h, has_alpha)."""
        from concurrent.futures import ThreadPoolExecutor

        FPS = 30
        MAX_FRAMES = FPS * 30

        frame_files = (self._bad_apple_frames or sorted(self.bad_apple_path.glob("*.jpg")))[frame_skip:frame_skip + MAX_FRAMES]
        if not frame_files:
            raise ValueError("No Bad Apple frames found")

        first = Image.open(frame_files[0])
        frame_w, frame_h = first.size

        t1 = self._build_tiled(avatar_bytes, frame_w, frame_h, tile_count)
        t1_rgb, t1_alpha = t1[:, :, :3], t1[:, :, 3]

        dual = avatar2_bytes is not None
        if dual:
            t2 = self._build_tiled(avatar2_bytes, frame_w, frame_h, tile_count)
            t2_rgb, t2_alpha = t2[:, :, :3], t2[:, :, 3]
        else:
            t2_rgb = t2_alpha = None

        workers = min(8, os.cpu_count() or 4)

        def load_mask(path):
            return np.array(Image.open(path).convert("L").resize((frame_w, frame_h), Image.Resampling.NEAREST))

        if delta_only:
            # Need all masks up front so each frame can reference the previous one
            with ThreadPoolExecutor(max_workers=workers) as ex:
                masks = list(ex.map(load_mask, frame_files))

            def composite(i):
                mask = masks[i]
                dark = mask < 128
                changed = np.abs(mask.astype(np.int16) - masks[i - 1].astype(np.int16)) > 20 if i > 0 else np.ones((frame_h, frame_w), dtype=bool)
                return _composite_frame(dark, changed, dual, frame_h, frame_w, t1_rgb, t1_alpha, t2_rgb, t2_alpha)

            with ThreadPoolExecutor(max_workers=workers) as ex:
                frame_bytes = list(ex.map(composite, range(len(frame_files))))
        else:
            # Single pass: load + composite together, no intermediate mask storage
            ones = np.ones((frame_h, frame_w), dtype=bool)

            def load_and_composite(path):
                mask = load_mask(path)
                return _composite_frame(mask < 128, ones, dual, frame_h, frame_w, t1_rgb, t1_alpha, t2_rgb, t2_alpha)

            with ThreadPoolExecutor(max_workers=workers) as ex:
                frame_bytes = list(ex.map(load_and_composite, frame_files))

        with open(raw_path, "wb") as f:
            f.writelines(frame_bytes)

        return frame_w, frame_h, not dual

    async def _detect_audio_offset(self, ffmpeg_exe: str) -> float:
        """Detect duration of silence at the start of the Bad Apple audio."""
        proc = await asyncio.create_subprocess_exec(
            ffmpeg_exe,
            "-i", str(self.bad_apple_audio_path),
            "-af", "silencedetect=n=-50dB:d=0.1",
            "-f", "null", "-",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        for line in stderr.decode().splitlines():
            if "silence_end" in line:
                try:
                    return float(line.split("silence_end:")[1].split("|")[0].strip())
                except (IndexError, ValueError):
                    pass
        return 0.0

    async def _encode_bad_apple_video(self, raw_path: str, frame_w: int, frame_h: int, has_alpha: bool = True, ffmpeg_exe: str = None, audio_offset: float = 0.0) -> io.BytesIO:
        """Encode raw frames + audio into MP4 (dual-user) or WebM with alpha (single-user)."""
        if ffmpeg_exe is None:
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

        suffix = ".webm" if has_alpha else ".mp4"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.close()
        out_path = tmp.name

        if has_alpha:
            video_flags = ["-vcodec", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", "-crf", "30", "-b:v", "0"]
        else:
            video_flags = ["-vcodec", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23"]

        # Use atrim filter to cut silence at sample level and reset timestamps to 0,
        # so the output file contains zero leading silence for players to strip.
        audio_filter = f"atrim=start={audio_offset:.6f},asetpts=PTS-STARTPTS" if audio_offset > 0 else "anull"

        cmd = [
            ffmpeg_exe, "-y",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{frame_w}x{frame_h}",
            "-pix_fmt", "rgba" if has_alpha else "rgb24", "-r", "30",
            "-i", raw_path,
            "-i", str(self.bad_apple_audio_path),
            "-map", "0:v", "-map", "1:a",
            "-af", audio_filter,
            *video_flags,
            "-t", "30",
            "-shortest",
            out_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

        with open(out_path, "rb") as f:
            video_bytes = f.read()

        os.unlink(out_path)
        os.unlink(raw_path)

        return io.BytesIO(video_bytes)


async def setup(bot):
    await bot.add_cog(AvatarCommands(bot))