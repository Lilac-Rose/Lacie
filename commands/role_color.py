import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path
import traceback

DEBUG = True

COLOR_ROLES = [
    "Turquoise", "Green Sea", "Emerald", "Nephritis", "River", "Belize",
    "Amethyst", "Wisteria", "Linen", "Alizarin", "Pomegranate", "Tangerine",
    "Rose", "Carrot", "Orange", "Sun Flower", "Pumpkin", "Light Gray",
    "Dark Air", "White"
]

class ColorRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    color_group = app_commands.Group(name="color", description="Manage your color role")

    @color_group.command(name="set", description="Choose your color role.")
    @app_commands.describe(color="The color role you'd like to have.")
    @app_commands.choices(color=[app_commands.Choice(name=name, value=name) for name in COLOR_ROLES])
    async def set_color(self, interaction: discord.Interaction, color: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        try:
            guild = interaction.guild
            member = interaction.user
            if not isinstance(member, discord.Member):
                member = guild.get_member(interaction.user.id) or await guild.fetch_member(interaction.user.id)

            selected_role = discord.utils.get(guild.roles, name=color.value)
            if not selected_role:
                await interaction.followup.send(f"⚠️ The role **{color.value}** doesn't exist on this server.", ephemeral=True)
                return

            previous = [r for r in member.roles if r.name in COLOR_ROLES]
            if previous:
                await member.remove_roles(*previous, reason="Changing color role")

            await member.add_roles(selected_role, reason="User selected a color role")
            await interaction.followup.send(
                f"✅ You now have the **{selected_role.name}** color role!",
                ephemeral=True
            )
        except Exception as e:
            print(f"[ERROR] /color set\n{traceback.format_exc()}")
            msg = f"❌ Error: `{e}`" if DEBUG else "❌ Something went wrong."
            await interaction.followup.send(msg, ephemeral=True)

    @color_group.command(name="remove", description="Remove your current color role.")
    async def remove_color(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            guild = interaction.guild
            member = interaction.user
            if not isinstance(member, discord.Member):
                member = guild.get_member(interaction.user.id) or await guild.fetch_member(interaction.user.id)

            color_roles = [r for r in member.roles if r.name in COLOR_ROLES]
            
            if not color_roles:
                await interaction.followup.send(
                    "ℹ️ You don't have any color role to remove.",
                    ephemeral=True
                )
                return

            await member.remove_roles(*color_roles, reason="User removed color role")
            removed_names = ", ".join([r.name for r in color_roles])
            await interaction.followup.send(
                f"✅ Removed your color role(s): **{removed_names}**",
                ephemeral=True
            )
        except Exception as e:
            print(f"[ERROR] /color remove\n{traceback.format_exc()}")
            msg = f"❌ Error: `{e}`" if DEBUG else "❌ Something went wrong."
            await interaction.followup.send(msg, ephemeral=True)

    @color_group.command(name="list", description="Show all available color images (visual palette).")
    async def list_colors(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        try:
            # Get absolute path to project root (parent of commands/)
            media_dir = Path(__file__).resolve().parent.parent / "media"
            if not media_dir.exists():
                raise FileNotFoundError(f"Media folder not found: {media_dir}")
            
            # Look for specific color image files only
            color_image_files = []
            for filename in ["colorimage1.png", "colorimage2.png"]:
                img_path = media_dir / filename
                if img_path.exists():
                    color_image_files.append(img_path)
            
            if not color_image_files:
                raise FileNotFoundError(f"Color images not found in {media_dir}")
            
            # Send first embed with first image
            file1 = discord.File(color_image_files[0], filename=color_image_files[0].name)
            embed1 = discord.Embed(
                title="🎨 Available Color Roles (Part 1)",
                description="Use `/color set` to pick one!",
                color=discord.Color.purple()
            )
            embed1.set_image(url=f"attachment://{color_image_files[0].name}")
            
            await interaction.followup.send(embed=embed1, file=file1, ephemeral=False)
            
            # Send second embed with second image if it exists
            if len(color_image_files) > 1:
                file2 = discord.File(color_image_files[1], filename=color_image_files[1].name)
                embed2 = discord.Embed(
                    title="🎨 Available Color Roles (Part 2)",
                    description="More colors to choose from!",
                    color=discord.Color.purple()
                )
                embed2.set_image(url=f"attachment://{color_image_files[1].name}")
                
                await interaction.followup.send(embed=embed2, file=file2, ephemeral=False)
                
        except Exception as e:
            print(f"[ERROR] /color list\n{traceback.format_exc()}")
            msg = f"❌ Error in `/color list`: `{e}`" if DEBUG else "❌ Something went wrong loading color images."
            await interaction.followup.send(msg, ephemeral=True)

async def setup(bot):
    await bot.add_cog(ColorRoles(bot))