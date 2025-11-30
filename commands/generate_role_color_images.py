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
from commands.role_color import DEBUG, COLOR_ROLE_NAMES, FONTS_PATH

class ColorImageGen(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="colorlist")
    @commands.has_role(ADMIN_ROLE_ID)
    async def generate_list(self, ctx):
        try:
            # boring setup
            guild = ctx.guild
            i = 0
            color_roles = []

            # Styling
            font_path_ttf = os.path.join(self.FONTS_PATH, f"Renogare-Regular.otf")
            FONT_SIZE = 80
            font = ImageFont.truetype(font_path_ttf, FONT_SIZE)
            COLUMN_SIZE = 4
            X_PADDING_PER_WORD = 100
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
                if longest_length < temp_draw.textlength(text, font=font): longest_length = temp_draw.textlength(text, font=font)
                i += 1

            # Draw the actual image
            img_width, img_height = int((longest_length + X_PADDING) * (ceil(len(self.COLOR_ROLE_NAMES) / COLUMN_SIZE))), COLUMN_SIZE * (FONT_SIZE + Y_PADDING) + 20
            img = Image.new("RGBA", (img_width, img_height))
            draw = ImageDraw.Draw(img)
            i = 0

            for color_role in color_roles:
                x_pos = (longest_length * (floor(i / COLUMN_SIZE)))
                if i >= COLUMN_SIZE:
                    x_pos += X_PADDING_PER_WORD * floor(i / COLUMN_SIZE)
                text = f"{i + 1}. {color_role.name}"
                draw.text((x_pos, (FONT_SIZE + Y_PADDING) * (i % COLUMN_SIZE)), text, font=font, fill=color_role.color.to_rgb())
                i += 1
            
            # Send message
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)
            await ctx.send(file=discord.File(buffer, "color_roles.png"))
                
        except Exception as e:
            print(f"[ERROR] /color list\n{traceback.format_exc()}")
            msg = f"❌ Error in `/color list`: `{e}`" if self.DEBUG else "❌ Something went wrong loading color images."
            await ctx.send(msg)

async def setup(bot):
    await bot.add_cog(ColorImageGen(bot))
