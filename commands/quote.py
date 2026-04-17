import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import asyncio
import io
import re
import math
import numpy as np
from datetime import timezone
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from utils.logger import get_logger

logger = get_logger(__name__)

FONT_DIR   = Path(__file__).parent.parent / "profiles" / "fonts"
MAX_CHARS  = 600

WIDTH      = 1200
HEIGHT     = 630
LEFT_W     = 560    # avatar panel width
FADE_FROM  = 0.82   # fade starts at 82% of LEFT_W (~38% of total canvas)
ANGLE_DEG  = 5      # degrees the fade edge is tilted

BG_COLOR     = (0, 0, 0)
TEXT_COLOR   = (255, 255, 255)
MUTED_COLOR  = (160, 160, 160)
FOOTER_COLOR = (90, 90, 90)


def _make_circle(data: bytes, size: int) -> Image.Image:
    img = Image.open(io.BytesIO(data)).convert("RGBA").resize(
        (size, size), Image.Resampling.LANCZOS
    )
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(img, mask=mask)
    return result


def _wrap(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, max_px: int) -> list[str]:
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    words = text.split(" ")
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        test = " ".join(current + [word])
        w = dummy.textbbox((0, 0), test, font=font)[2]
        if w > max_px and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _clean_content(content: str, guild: discord.Guild | None) -> str:
    def sub_user(m: re.Match) -> str:
        if not guild:
            return f"@{m.group(1)}"
        member = guild.get_member(int(m.group(1)))
        return f"@{member.display_name}" if member else f"@{m.group(1)}"

    def sub_channel(m: re.Match) -> str:
        if not guild:
            return f"<#{m.group(1)}>"
        ch = guild.get_channel(int(m.group(1)))
        return f"#{ch.name}" if ch else f"<#{m.group(1)}>"

    def sub_role(m: re.Match) -> str:
        if not guild:
            return f"@{m.group(1)}"
        role = guild.get_role(int(m.group(1)))
        return f"@{role.name}" if role else f"@{m.group(1)}"

    content = re.sub(r"<@!?(\d+)>", sub_user, content)
    content = re.sub(r"<#(\d+)>", sub_channel, content)
    content = re.sub(r"<@&(\d+)>", sub_role, content)
    content = re.sub(r"<a?:([^:]+):\d+>", r":\1:", content)
    return content


def _pick_body_font(char_count: int) -> int:
    """Return a font size that keeps the quote readable at different lengths."""
    if char_count <= 80:
        return 54
    if char_count <= 160:
        return 44
    if char_count <= 280:
        return 36
    return 28


def _render(
    avatar_data: bytes,
    display_name: str,
    username: str,
    content: str,
    timestamp: str,
    channel_name: str,
    grayscale: bool = False,
) -> bytes:
    # ── fonts ──────────────────────────────────────────────────────────────────
    try:
        renogare = str(FONT_DIR / "Renogare-Regular.otf")
        notosans  = str(FONT_DIR / "NotoSans-Regular.ttf")
        body_size   = _pick_body_font(len(content))
        font_body   = ImageFont.truetype(renogare,  body_size)
        font_name   = ImageFont.truetype(renogare,  28)
        font_handle = ImageFont.truetype(notosans,  19)
        font_footer = ImageFont.truetype(notosans,  15)
    except Exception:
        font_body = font_name = font_handle = font_footer = ImageFont.load_default()

    if len(content) > MAX_CHARS:
        content = content[:MAX_CHARS].rstrip() + "\u2026"

    # ── canvas ─────────────────────────────────────────────────────────────────
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)

    # ── avatar panel (left, fades to black) ────────────────────────────────────
    av_raw = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
    aw, ah = av_raw.size
    scale  = max(LEFT_W / aw, HEIGHT / ah)
    nw, nh = int(aw * scale), int(ah * scale)
    av_raw = av_raw.resize((nw, nh), Image.Resampling.LANCZOS)
    cx = (nw - LEFT_W) // 2
    cy = (nh - HEIGHT)  // 2
    av_raw = av_raw.crop((cx, cy, cx + LEFT_W, cy + HEIGHT))

    # angled gradient mask: opaque left → transparent right, tilted by ANGLE_DEG
    fade_base  = int(LEFT_W * FADE_FROM)
    fade_range = max(1, LEFT_W - fade_base)
    angle_rad  = math.radians(ANGLE_DEG)

    ys = np.arange(HEIGHT, dtype=np.float32).reshape(-1, 1)
    xs = np.arange(LEFT_W, dtype=np.float32).reshape(1, -1)

    # fade line shifts right at the bottom, left at the top
    fade_at = fade_base + (ys - HEIGHT / 2) * np.tan(angle_rad)
    rel     = (xs - fade_at) / fade_range
    alpha   = np.clip(1.0 - rel, 0.0, 1.0) * 255

    grad = Image.fromarray(alpha.astype(np.uint8), mode="L")
    img.paste(av_raw.convert("RGB"), (0, 0), grad)

    d = ImageDraw.Draw(img)

    # ── text area (right half) ──────────────────────────────────────────────────
    PAD_X       = 55
    text_left   = LEFT_W + PAD_X
    text_right  = WIDTH  - PAD_X
    text_w      = text_right - text_left
    center_x    = (LEFT_W + WIDTH) // 2

    # measure helpers
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    body_lh = dummy.textbbox((0, 0), "Ag", font=font_body)
    body_line_h = (body_lh[3] - body_lh[1]) + 8

    name_lh  = dummy.textbbox((0, 0), "Ag", font=font_name)
    name_h   = name_lh[3] - name_lh[1]
    hndl_lh  = dummy.textbbox((0, 0), "Ag", font=font_handle)
    hndl_h   = hndl_lh[3] - hndl_lh[1]

    AV_SM    = 26   # small attribution avatar size
    ATTR_GAP = 22   # gap between body and attribution row
    ROW_GAP  = 8    # gap between name row and handle row

    body_lines  = _wrap(content, font_body, text_w)
    total_h = (
        len(body_lines) * body_line_h
        + ATTR_GAP
        + max(AV_SM, name_h)
        + ROW_GAP
        + hndl_h
    )
    start_y = (HEIGHT - total_h) // 2

    # body text — center-aligned
    y = start_y
    for line in body_lines:
        bbox = dummy.textbbox((0, 0), line, font=font_body)
        lw   = bbox[2] - bbox[0]
        d.text((center_x - lw // 2, y), line, font=font_body, fill=TEXT_COLOR)
        y += body_line_h

    # attribution row: "- [avatar] display_name"
    attr_y = y + ATTR_GAP

    small_av = _make_circle(avatar_data, AV_SM)

    dash   = "- "
    dash_w = dummy.textbbox((0, 0), dash, font=font_name)[2]
    name_w = dummy.textbbox((0, 0), display_name, font=font_name)[2]
    row_w  = dash_w + AV_SM + 6 + name_w
    row_x  = center_x - row_w // 2

    av_off_y = attr_y + (name_h - AV_SM) // 2

    d.text((row_x, attr_y), dash, font=font_name, fill=TEXT_COLOR)
    img.paste(small_av, (row_x + dash_w, max(attr_y, av_off_y)), small_av)
    d.text((row_x + dash_w + AV_SM + 6, attr_y), display_name, font=font_name, fill=TEXT_COLOR)

    # @handle
    handle_y  = attr_y + max(name_h, AV_SM) + ROW_GAP
    handle_tx = f"@{username}"
    hw        = dummy.textbbox((0, 0), handle_tx, font=font_handle)[2]
    d.text((center_x - hw // 2, handle_y), handle_tx, font=font_handle, fill=MUTED_COLOR)

    # watermark — bottom right
    wm   = timestamp
    wm_w = dummy.textbbox((0, 0), wm, font=font_footer)[2]
    d.text((WIDTH - PAD_X - wm_w, HEIGHT - 28), wm, font=font_footer, fill=FOOTER_COLOR)

    if grayscale:
        img = img.convert("L").convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


class Quote(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    @app_commands.command(name="quote", description="Turn a message into a quote image")
    @app_commands.describe(
        message_id="The ID of the message to quote",
        channel="The channel the message is in (defaults to the current channel)",
        channel_id="Channel or thread ID — use this for threads or channels not in the list",
        grayscale="Render the image in grayscale",
    )
    async def quote(
        self,
        interaction: discord.Interaction,
        message_id: str,
        channel: discord.TextChannel | None = None,
        channel_id: str | None = None,
        grayscale: bool = False,
    ):
        await interaction.response.defer()

        # Resolve target channel / thread
        target: discord.abc.Messageable
        channel_name: str
        joined_thread: discord.Thread | None = None

        if channel_id is not None:
            try:
                raw_id = int(channel_id)
            except ValueError:
                await interaction.followup.send("That doesn't look like a valid channel ID.", ephemeral=True)
                return
            resolved = self.bot.get_channel(raw_id) or await self.bot.fetch_channel(raw_id)
            if not isinstance(resolved, discord.abc.Messageable):
                await interaction.followup.send("That channel ID didn't resolve to a readable channel.", ephemeral=True)
                return
            target = resolved
            channel_name = resolved.name if hasattr(resolved, "name") else str(raw_id)
        elif channel is not None:
            target = channel
            channel_name = channel.name
        elif isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            target = interaction.channel
            channel_name = interaction.channel.name
        else:
            await interaction.followup.send(
                "This command can only be used in a text channel or thread.", ephemeral=True
            )
            return

        # Join threads the bot isn't already a member of
        if isinstance(target, discord.Thread) and not target.me:
            await target.join()
            joined_thread = target

        try:
            try:
                msg_id = int(message_id)
            except ValueError:
                await interaction.followup.send("That doesn't look like a valid message ID.", ephemeral=True)
                return

            try:
                message = await target.fetch_message(msg_id)
            except discord.NotFound:
                await interaction.followup.send(
                    "Message not found. Make sure the ID is correct and the channel is right.",
                    ephemeral=True,
                )
                return
            except discord.Forbidden:
                await interaction.followup.send("I don't have permission to read that channel.", ephemeral=True)
                return

            content = message.content
            if not content:
                if message.attachments:
                    n = len(message.attachments)
                    content = f"[{n} attachment{'s' if n > 1 else ''}]"
                elif message.embeds:
                    content = "[embed]"
                elif message.stickers:
                    content = f"[sticker: {message.stickers[0].name}]"
                else:
                    await interaction.followup.send("That message has no quotable content.", ephemeral=True)
                    return

            content = _clean_content(content, interaction.guild)

            author = message.author
            display_name = (
                author.display_name
                if isinstance(author, discord.Member)
                else (author.global_name or author.name)
            )
            username = author.name

            ts = message.created_at.replace(tzinfo=timezone.utc).strftime("%-d %b %Y")

            assert self.session is not None
            async with self.session.get(author.display_avatar.url) as resp:
                avatar_data = await resp.read()

            image_bytes = await asyncio.to_thread(
                _render, avatar_data, display_name, username, content, ts, channel_name, grayscale
            )

            await interaction.followup.send(
                file=discord.File(io.BytesIO(image_bytes), filename="quote.png")
            )

        finally:
            if joined_thread:
                await joined_thread.leave()


async def setup(bot: commands.Bot):
    await bot.add_cog(Quote(bot))
