import discord
from discord.ext import commands
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont
import aiohttp
import io
import os
import asyncio
from textwrap import wrap
from .database import get_db, setup_db

FONTS_PATH = os.path.join(os.path.dirname(__file__), "fonts")

def list_fonts():
    fonts = []
    if os.path.exists(FONTS_PATH):
        for f in os.listdir(FONTS_PATH):
            if f.lower().endswith((".ttf", ".otf")):
                fonts.append(os.path.splitext(f)[0])
    return fonts

class Profiles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        setup_db()

    @app_commands.command(name="listfonts", description="List all avaliable fonts for profiles.")
    async def list_fonts_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        
        fonts = list_fonts()
        if not fonts:
            await interaction.followup.send("No fonts found in the fonts folder.")
            return
        await interaction.followup.send("**Avaliable Fonts:**\n" + "\n".join(f"- `{f}`" for f in fonts))

    @app_commands.command(name="setprofile", description="Set your profile information.")
    @app_commands.describe(
        pronouns="Your pronouns",
        about_me="A short description about you",
        fav_color="Your favorite color (name or hex)",
        bg_color="Background color (hex with #, e.g. #FF5733)",
        fav_game="Your favorite game",
        fav_artist="Your favorite music artist",
        birthday="Your birthday (MM-DD)",
        font_name="Font to use (see /listfonts)"
    )
    async def setprofile(self, interaction: discord.Interaction,
                        pronouns: str = None,
                        about_me: str = None,
                        fav_color: str = None,
                        bg_color: str = None,
                        fav_game: str = None,
                        fav_artist: str = None,
                        birthday: str = None,
                        font_name: str = None):
        
        # Defer the response to show "thinking"
        await interaction.response.defer(thinking=True)
        
        # Validate bg_color format
        if bg_color is not None:
            if not bg_color.startswith('#') or len(bg_color) not in [4, 7]:
                await interaction.followup.send("Background color must be a hex color starting with # (e.g. #FF5733 or #F57)")
                return
            # Validate hex characters
            try:
                int(bg_color[1:], 16)
            except ValueError:
                await interaction.followup.send("Invalid hex color format. Use # followed by hex digits (e.g. #FF5733)")
                return
        
        if font_name and font_name not in list_fonts():
            await interaction.followup.send("That font is not avaliable. use /listfonts to see the options.")
            return
        
        db = get_db()
        cursor = db.cursor()

        # Build update query dynamically to only update provided fields
        update_fields = []
        values = []
        
        if pronouns is not None:
            update_fields.append("pronouns = ?")
            values.append(pronouns)
        if about_me is not None:
            update_fields.append("about_me = ?")
            values.append(about_me)
        if fav_color is not None:
            update_fields.append("fav_color = ?")
            values.append(fav_color)
        if bg_color is not None:
            update_fields.append("bg_color = ?")
            values.append(bg_color)
        if fav_game is not None:
            update_fields.append("fav_game = ?")
            values.append(fav_game)
        if fav_artist is not None:
            update_fields.append("fav_artist = ?")
            values.append(fav_artist)
        if birthday is not None:
            update_fields.append("birthday = ?")
            values.append(birthday)
        if font_name is not None:
            update_fields.append("font_name = ?")
            values.append(font_name)
        
        if not update_fields:
            await interaction.followup.send("Please provide at least one field to update!")
            db.close()
            return
        
        # Check if user exists
        cursor.execute("SELECT user_id FROM profiles WHERE user_id = ?", (interaction.user.id,))
        exists = cursor.fetchone()
        
        if exists:
            # Update existing profile
            query = f"UPDATE profiles SET {', '.join(update_fields)} WHERE user_id = ?"
            values.append(interaction.user.id)
            cursor.execute(query, values)
        else:
            # Insert new profile with only provided fields
            fields = ["user_id"] + [field.split(" = ")[0] for field in update_fields]
            placeholders = ["?"] * len(fields)
            query = f"INSERT INTO profiles ({', '.join(fields)}) VALUES ({', '.join(placeholders)})"
            cursor.execute(query, [interaction.user.id] + values)

        db.commit()
        db.close()

        await interaction.followup.send("Your profile has been saved!")

    @app_commands.command(name="profile", description="View your or another user's profile.")
    async def profile(self, interaction: discord.Interaction, member: discord.Member = None):
        # Defer immediately to show "thinking"
        await interaction.response.defer(thinking=True)
        
        member = member or interaction.user

        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM profiles WHERE user_id=?", (member.id,))
        row = cursor.fetchone()
        db.close()

        if not row:
            await interaction.followup.send("This user hasn't set up a profile yet. Use /setprofile to add information to your profile")
            return
        
        _, pronouns, about_me, fav_color, bg_color, fav_game, fav_artist, birthday, font_name = row

        avatar_asset = member.display_avatar.with_size(256)
        avatar_bytes = await avatar_asset.read()

        def generate_image():
            try:
                if font_name:
                    # Try .ttf first, then .otf
                    font_path_ttf = os.path.join(FONTS_PATH, f"{font_name}.ttf")
                    font_path_otf = os.path.join(FONTS_PATH, f"{font_name}.otf")
                    
                    if os.path.exists(font_path_ttf):
                        font = ImageFont.truetype(font_path_ttf, 20)
                        font_bold = ImageFont.truetype(font_path_ttf, 32)
                        font_label = ImageFont.truetype(font_path_ttf, 20)
                    elif os.path.exists(font_path_otf):
                        font = ImageFont.truetype(font_path_otf, 20)
                        font_bold = ImageFont.truetype(font_path_otf, 32)
                        font_label = ImageFont.truetype(font_path_otf, 20)
                    else:
                        font = ImageFont.load_default()
                        font_bold = ImageFont.load_default()
                        font_label = ImageFont.load_default()
                else:
                    font = ImageFont.load_default()
                    font_bold = ImageFont.load_default()
                    font_label = ImageFont.load_default()
            except Exception:
                font = ImageFont.load_default()
                font_bold = ImageFont.load_default()
                font_label = ImageFont.load_default()

            img_width, img_height = 1000, 550
            
            # Parse background color - only accept hex with #
            base_color = "#0f1419"  # default
            if bg_color and bg_color.startswith('#'):
                try:
                    # Validate it's a proper hex color
                    int(bg_color[1:], 16)
                    base_color = bg_color
                except:
                    pass  # Use default if invalid
            
            img = Image.new("RGB", (img_width, img_height), base_color)
            draw = ImageDraw.Draw(img)
            
            # Draw semi-transparent panel for avatar section
            panel_left_x = 30
            panel_left_width = 290
            draw.rounded_rectangle(
                [(panel_left_x, 30), (panel_left_x + panel_left_width, 470)],
                radius=20,
                fill=(40, 45, 52, 200)
            )

            # Avatar setup - centered in left panel
            avatar_size = 200
            panel_center = panel_left_x + panel_left_width // 2
            avatar_x = panel_center - avatar_size // 2
            avatar_y = 60
            
            # Draw glowing border around avatar
            for offset in range(3):
                draw.rounded_rectangle(
                    [(avatar_x - 6 - offset, avatar_y - 6 - offset), 
                     (avatar_x + avatar_size + 6 + offset, avatar_y + avatar_size + 6 + offset)],
                    radius=15,
                    outline=(88, 101, 242, 100 - offset * 30),
                    width=2
                )

            # Paste avatar with rounded corners
            avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar = avatar.resize((avatar_size, avatar_size))
            
            mask = Image.new('L', (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([(0, 0), (avatar_size, avatar_size)], radius=12, fill=255)
            
            img.paste(avatar, (avatar_x, avatar_y), mask)

            # Draw username with shadow effect - centered in panel with dynamic sizing
            username_y = avatar_y + avatar_size + 25
            
            # Dynamically scale font size to fit username in panel
            max_username_width = panel_left_width - 20  # Leave some padding
            username_font = font_bold
            username_font_size = 32
            
            # Keep reducing font size until it fits
            while username_font_size > 16:
                try:
                    if font_name:
                        font_path_ttf = os.path.join(FONTS_PATH, f"{font_name}.ttf")
                        font_path_otf = os.path.join(FONTS_PATH, f"{font_name}.otf")
                        
                        if os.path.exists(font_path_ttf):
                            username_font = ImageFont.truetype(font_path_ttf, username_font_size)
                        elif os.path.exists(font_path_otf):
                            username_font = ImageFont.truetype(font_path_otf, username_font_size)
                        else:
                            username_font = ImageFont.load_default()
                            break
                    else:
                        username_font = ImageFont.load_default()
                        break
                except:
                    username_font = ImageFont.load_default()
                    break
                
                # Check if username fits
                bbox = draw.textbbox((0, 0), member.display_name, font=username_font)
                text_width = bbox[2] - bbox[0]
                
                if text_width <= max_username_width:
                    break
                    
                username_font_size -= 2
            
            # Shadow
            draw.text((panel_center + 2, username_y + 2), member.display_name, 
                     fill=(0, 0, 0, 100), font=username_font, anchor="mt")
            # Main text
            draw.text((panel_center, username_y), member.display_name, 
                     fill="#FFFFFF", font=username_font, anchor="mt")
            
            # Draw pronouns below username if available - centered in panel
            current_y = username_y + 40
            if pronouns:
                draw.text((panel_center, current_y), pronouns, 
                         fill="#B9BBBE", font=font, anchor="mt")
                current_y += 35
            
            # Draw roles below pronouns
            roles = [role for role in member.roles if role.name != "@everyone"]
            if roles:
                # Sort roles by position (highest first, like Discord does)
                roles.sort(key=lambda r: r.position, reverse=True)
                
                # Limit to top 5 roles to avoid overflow
                display_roles = roles[:5]
                
                role_y = current_y
                role_font_size = 14
                try:
                    if font_name:
                        font_path_ttf = os.path.join(FONTS_PATH, f"{font_name}.ttf")
                        font_path_otf = os.path.join(FONTS_PATH, f"{font_name}.otf")
                        
                        if os.path.exists(font_path_ttf):
                            role_font = ImageFont.truetype(font_path_ttf, role_font_size)
                        elif os.path.exists(font_path_otf):
                            role_font = ImageFont.truetype(font_path_otf, role_font_size)
                        else:
                            role_font = ImageFont.load_default()
                    else:
                        role_font = ImageFont.load_default()
                except:
                    role_font = ImageFont.load_default()
                
                for role in display_roles:
                    # Get role color (use white if no color)
                    role_color = role.color.to_rgb() if role.color.value != 0 else (185, 187, 190)
                    
                    # Draw role name centered
                    role_text = f"• {role.name}"
                    draw.text((panel_center, role_y), role_text, 
                             fill=role_color, font=role_font, anchor="mt")
                    role_y += 22

            # Right side panel
            panel_x = 360
            panel_y = 50
            panel_width = img_width - panel_x - 40
            
            # Draw semi-transparent panel for info
            draw.rounded_rectangle(
                [(panel_x - 20, 30), (img_width - 30, 470)],
                radius=20,
                fill=(40, 45, 52, 150)
            )

            line_spacing = 50
            max_text_width = panel_width - 60

            fields = [
                ("Favorite Color", fav_color),
                ("Favorite Game", fav_game),
                ("Favorite Artist", fav_artist),
                ("Birthday", birthday),
                ("About Me", about_me)
            ]

            for label, value in fields:
                if value:
                    if label == "About Me":
                        # Draw label and value on same line
                        draw.text((panel_x, panel_y), f"{label}: ", fill="#7289DA", font=font_label)
                        
                        # Calculate label width to position value text
                        label_bbox = draw.textbbox((0, 0), f"{label}: ", font=font_label)
                        label_width = label_bbox[2] - label_bbox[0]
                        value_x = panel_x + label_width
                        
                        # Wrap About Me text
                        words = value.split()
                        line = ""
                        first_line = True
                        for word in words:
                            test_line = f"{line} {word}".strip()
                            bbox = draw.textbbox((0, 0), test_line, font=font)
                            line_width = bbox[2] - bbox[0]
                            available_width = max_text_width - (label_width if first_line else 0)
                            
                            if line_width <= available_width:
                                line = test_line
                            else:
                                if line:
                                    draw.text((value_x if first_line else panel_x, panel_y), line, fill="#FFFFFF", font=font)
                                    panel_y += 30
                                    first_line = False
                                    value_x = panel_x
                                line = word
                        if line:
                            draw.text((value_x if first_line else panel_x, panel_y), line, fill="#FFFFFF", font=font)
                            panel_y += line_spacing
                    else:
                        # Draw label and value on same line
                        draw.text((panel_x, panel_y), f"{label}: ", fill="#7289DA", font=font_label)
                        
                        # Calculate label width to position value text
                        label_bbox = draw.textbbox((0, 0), f"{label}: ", font=font_label)
                        label_width = label_bbox[2] - label_bbox[0]
                        
                        # Draw value right after label
                        draw.text((panel_x + label_width, panel_y), str(value), fill="#FFFFFF", font=font)
                        panel_y += line_spacing

            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)
            return buffer

        buffer = await asyncio.to_thread(generate_image)
        await interaction.followup.send(file=discord.File(buffer, "profile.png"))

async def setup(bot):
    await bot.add_cog(Profiles(bot))