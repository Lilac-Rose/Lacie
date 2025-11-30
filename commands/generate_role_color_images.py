import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path
import traceback
from PIL import Image, ImageDraw, ImageFont
import os
import io
from math import floor, ceil
from moderation.loader import ModerationBase, ADMIN_ROLE_ID
import importlib
import sys

class ColorImageGen(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Import and get fresh references on initialization
        self._reload_config()
    
    def _reload_config(self):
        """Reload configuration from role_color module"""
        # Force reload the role_color module to get fresh values
        if 'commands.role_color' in sys.modules:
            role_color_module = importlib.reload(sys.modules['commands.role_color'])
        else:
            import commands.role_color as role_color_module
        
        # Store as instance variables
        self.DEBUG = role_color_module.DEBUG
        self.COLOR_ROLE_NAMES = role_color_module.COLOR_ROLE_NAMES
        self.FONTS_PATH = role_color_module.FONTS_PATH

    @commands.command(name="generateimages")
    @commands.has_role(ADMIN_ROLE_ID)
    async def generate_list(self, ctx):
        # Reload config to get latest values
        self._reload_config()
        
        try:
            # boring setup
            guild = ctx.guild
            i = 0
            color_roles = []
            
            # Styling
            font_path_ttf = os.path.join(self.FONTS_PATH, "Renogare-Regular.otf")
            FONT_SIZE = 300
            font = ImageFont.truetype(font_path_ttf, FONT_SIZE)
            COLUMN_SIZE = 5
            X_PADDING_PER_COLUMN = 100
            X_PADDING = 200
            Y_PADDING = 10
            
            # Check longest length
            temp_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            longest_length = 0
            for color_role_name in self.COLOR_ROLE_NAMES:
                color_role = discord.utils.get(guild.roles, name=color_role_name)
                color_roles.append(color_role)
                if not color_role:
                    await ctx.send(f"⚠️ The role **{color_role_name}** doesn't exist on this server.")
                    return
                
                text = f"{i + 1}. {color_role_name}"
                if longest_length < temp_draw.textlength(text, font=font): 
                    longest_length = temp_draw.textlength(text, font=font)
                i += 1
            
            # Draw the actual image
            img_width = int((longest_length + X_PADDING) * (ceil(len(self.COLOR_ROLE_NAMES) / COLUMN_SIZE)))
            img_height = COLUMN_SIZE * (FONT_SIZE + Y_PADDING) + 20
            img = Image.new("RGBA", (img_width, img_height))
            draw = ImageDraw.Draw(img)
            
            i = 0
            for color_role in color_roles:
                x_pos = (longest_length * (floor(i / COLUMN_SIZE)))
                if i >= COLUMN_SIZE:
                    x_pos += X_PADDING_PER_COLUMN * floor(i / COLUMN_SIZE)
                text = f"{i + 1}. {color_role.name}"
                draw.text(
                    (x_pos, (FONT_SIZE + Y_PADDING) * (i % COLUMN_SIZE)), 
                    text, 
                    font=font, 
                    fill=color_role.color.to_rgb()
                )
                i += 1
            
            # Get path to media directory (parent of commands/)
            media_dir = Path(__file__).resolve().parent.parent / "media"
            media_dir.mkdir(exist_ok=True)  # Create media folder if it doesn't exist
            
            # Save to file (overwrites if exists)
            output_path = media_dir / "colorimage.png"
            img.save(output_path, format="PNG")
            
            # Also send as message for preview
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)
            await ctx.send(
                f"✅ Color image generated and saved to `{output_path}`",
                file=discord.File(buffer, "colorimage.png")
            )
                
        except Exception as e:
            print(f"[ERROR] /color list\n{traceback.format_exc()}")
            msg = f"❌ Error in `/color list`: `{e}`" if self.DEBUG else "❌ Something went wrong loading color images."
            await ctx.send(msg)

async def setup(bot):
    await bot.add_cog(ColorImageGen(bot))