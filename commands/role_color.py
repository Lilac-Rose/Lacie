import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import io
from math import floor, ceil
from moderation.loader import ModerationBase
from embed.embed_color import get_embed_color
from utils.logger import get_logger

logger = get_logger(__name__)

DEBUG = False

# keep this list in sync with the actual roles on the server
# generate_role_color_images.py reads from this too, so order matters for the image layout
COLOR_ROLE_NAMES = [
    "Turquoise", "Green Sea", "Emerald", "Nephritis", "River", "Belize",
    "Amethyst", "Wisteria", "Linen", "Alizarin", "Pomegranate", "Tangerine",
    "Rose", "Carrot", "Orange", "Sun Flower", "Pumpkin", "Light Gray",
    "Dark Air", "White-ish"
]

FONTS_PATH = Path(__file__).parent.parent / "fonts"

class ColorRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    color_group = app_commands.Group(name="color", description="Manage your color role")

    @color_group.command(name="set", description="Choose your color role.")
    @app_commands.describe(color="The color role you'd like to have.")
    @app_commands.choices(color=[app_commands.Choice(name=name, value=name) for name in COLOR_ROLE_NAMES])
    async def set_color(self, interaction: discord.Interaction, color: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
                return

            member = interaction.user
            if not isinstance(member, discord.Member):
                # interaction.user can come back as a User in some edge cases, so fetch the full Member
                try:
                    member = await guild.fetch_member(interaction.user.id)
                except discord.NotFound:
                    await interaction.followup.send("Could not find your member profile.", ephemeral=True)
                    return

            selected_role = discord.utils.get(guild.roles, name=color.value)
            if not selected_role:
                await interaction.followup.send(f"The role **{color.value}** doesn't exist on this server.", ephemeral=True)
                return

            # Check bot permissions
            bot_member = guild.me
            if not bot_member.guild_permissions.manage_roles:
                await interaction.followup.send("I don't have permission to manage roles.", ephemeral=True)
                return

            if selected_role >= bot_member.top_role:
                await interaction.followup.send("I cannot assign this role because it's higher than or equal to my highest role.", ephemeral=True)
                return

            # strip off any existing color roles before assigning the new one
            previous = [r for r in member.roles if r.name in COLOR_ROLE_NAMES]
            if previous:
                try:
                    await member.remove_roles(*previous, reason="Changing color role")
                except discord.Forbidden:
                    await interaction.followup.send("I don't have permission to remove your current color roles.", ephemeral=True)
                    return
                except discord.HTTPException as e:
                    await interaction.followup.send(f"Failed to remove previous roles: {str(e)}", ephemeral=True)
                    return

            # Add new color role
            try:
                await member.add_roles(selected_role, reason="User selected a color role")
            except discord.Forbidden:
                await interaction.followup.send("I don't have permission to assign this role.", ephemeral=True)
                return
            except discord.HTTPException as e:
                await interaction.followup.send(f"Failed to assign role: {str(e)}", ephemeral=True)
                return

            await interaction.followup.send(
                f"You now have the **{selected_role.name}** color role!",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"/color set: {e}", exc_info=True)
            msg = f"Error: `{e}`" if DEBUG else "Something went wrong."
            await interaction.followup.send(msg, ephemeral=True)

    @color_group.command(name="setfor", description="[ADMIN] Set a color role for another user.")
    @app_commands.describe(
        user="The user to set the color for.",
        color="The color role to assign."
    )
    @app_commands.choices(color=[app_commands.Choice(name=name, value=name) for name in COLOR_ROLE_NAMES])
    @ModerationBase.is_admin()
    async def set_color_for(self, interaction: discord.Interaction, user: discord.Member, color: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=False)
        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
                return

            selected_role = discord.utils.get(guild.roles, name=color.value)
            if not selected_role:
                await interaction.followup.send(f"The role **{color.value}** doesn't exist on this server.", ephemeral=True)
                return

            # Check bot permissions
            bot_member = guild.me
            if not bot_member.guild_permissions.manage_roles:
                await interaction.followup.send("I don't have permission to manage roles.", ephemeral=True)
                return

            if selected_role >= bot_member.top_role:
                await interaction.followup.send("I cannot assign this role because it's higher than or equal to my highest role.", ephemeral=True)
                return

            # Remove any existing color roles
            previous = [r for r in user.roles if r.name in COLOR_ROLE_NAMES]
            if previous:
                try:
                    await user.remove_roles(*previous, reason=f"Admin {interaction.user} changing color role")
                except discord.Forbidden:
                    await interaction.followup.send(f"I don't have permission to remove roles from {user.mention}.", ephemeral=True)
                    return
                except discord.HTTPException as e:
                    await interaction.followup.send(f"Failed to remove previous roles: {str(e)}", ephemeral=True)
                    return

            # Add the new color role
            try:
                await user.add_roles(selected_role, reason=f"Admin {interaction.user} set color role")
            except discord.Forbidden:
                await interaction.followup.send(f"I don't have permission to assign roles to {user.mention}.", ephemeral=True)
                return
            except discord.HTTPException as e:
                await interaction.followup.send(f"Failed to assign role: {str(e)}", ephemeral=True)
                return

            await interaction.followup.send(
                f"Set **{selected_role.name}** color role for {user.mention}!",
                ephemeral=False
            )
        except Exception as e:
            logger.error(f"/color setfor: {e}", exc_info=True)
            msg = f"Error: `{e}`" if DEBUG else "Something went wrong."
            await interaction.followup.send(msg, ephemeral=True)

    @color_group.command(name="remove", description="Remove your current color role.")
    async def remove_color(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
                return

            member = interaction.user
            if not isinstance(member, discord.Member):
                try:
                    member = await guild.fetch_member(interaction.user.id)
                except discord.NotFound:
                    await interaction.followup.send("Could not find your member profile.", ephemeral=True)
                    return

            color_roles = [r for r in member.roles if r.name in COLOR_ROLE_NAMES]

            if not color_roles:
                await interaction.followup.send(
                    "You don't have any color role to remove.",
                    ephemeral=True
                )
                return

            # Check bot permissions
            bot_member = guild.me
            if not bot_member.guild_permissions.manage_roles:
                await interaction.followup.send("I don't have permission to manage roles.", ephemeral=True)
                return

            try:
                await member.remove_roles(*color_roles, reason="User removed color role")
            except discord.Forbidden:
                await interaction.followup.send("I don't have permission to remove your color roles.", ephemeral=True)
                return
            except discord.HTTPException as e:
                await interaction.followup.send(f"Failed to remove roles: {str(e)}", ephemeral=True)
                return

            removed_names = ", ".join([r.name for r in color_roles])
            await interaction.followup.send(
                f"Removed your color role(s): **{removed_names}**",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"/color remove: {e}", exc_info=True)
            msg = f"Error: `{e}`" if DEBUG else "Something went wrong."
            await interaction.followup.send(msg, ephemeral=True)

    @color_group.command(name="removefor", description="[ADMIN] Remove color role(s) from another user.")
    @app_commands.describe(user="The user to remove color roles from.")
    @ModerationBase.is_admin()
    async def remove_color_for(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=False)
        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
                return

            color_roles = [r for r in user.roles if r.name in COLOR_ROLE_NAMES]

            if not color_roles:
                await interaction.followup.send(
                    f"{user.mention} doesn't have any color role to remove.",
                    ephemeral=False
                )
                return

            # Check bot permissions
            bot_member = guild.me
            if not bot_member.guild_permissions.manage_roles:
                await interaction.followup.send("I don't have permission to manage roles.", ephemeral=True)
                return

            try:
                await user.remove_roles(*color_roles, reason=f"Admin {interaction.user} removed color role")
            except discord.Forbidden:
                await interaction.followup.send(f"I don't have permission to remove roles from {user.mention}.", ephemeral=True)
                return
            except discord.HTTPException as e:
                await interaction.followup.send(f"Failed to remove roles: {str(e)}", ephemeral=True)
                return

            removed_names = ", ".join([r.name for r in color_roles])
            await interaction.followup.send(
                f"Removed color role(s) from {user.mention}: **{removed_names}**",
                ephemeral=False
            )
        except Exception as e:
            logger.error(f"/color removefor: {e}", exc_info=True)
            msg = f"Error: `{e}`" if DEBUG else "Something went wrong."
            await interaction.followup.send(msg, ephemeral=True)

    @color_group.command(name="list", description="Show all available role colors")
    async def list_colors(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        try:
            media_dir = Path(__file__).resolve().parent.parent / "media"
            if not media_dir.exists():
                raise FileNotFoundError(f"Media folder not found: {media_dir}")

            img_path = media_dir / "colorimage.png"

            if not img_path.exists():
                # fall back to the old split images if colorimage.png hasn't been generated yet
                color_image_files = []
                for filename in ["colorimage1.png", "colorimage2.png"]:
                    fallback_path = media_dir / filename
                    if fallback_path.exists():
                        color_image_files.append(fallback_path)

                if not color_image_files:
                    await interaction.followup.send(
                        "No color images found. An admin needs to run `!generateimages` first.",
                        ephemeral=True
                    )
                    return

                # Send old format with multiple images
                file1 = discord.File(color_image_files[0], filename=color_image_files[0].name)
                embed1 = discord.Embed(
                    title="Available Color Roles (Part 1)",
                    description="Use `/color set` to pick one!",
                    color=get_embed_color(interaction.user.id)
                )
                embed1.set_image(url=f"attachment://{color_image_files[0].name}")
                await interaction.followup.send(embed=embed1, file=file1, ephemeral=False)

                if len(color_image_files) > 1:
                    file2 = discord.File(color_image_files[1], filename=color_image_files[1].name)
                    embed2 = discord.Embed(
                        title="Available Color Roles (Part 2)",
                        description="More colors to choose from!",
                        color=get_embed_color(interaction.user.id)
                    )
                    embed2.set_image(url=f"attachment://{color_image_files[1].name}")
                    await interaction.followup.send(embed=embed2, file=file2, ephemeral=False)
            else:
                # Send the generated colorimage.png
                file = discord.File(img_path, filename="colorimage.png")
                embed = discord.Embed(
                    title="Available Color Roles",
                    description="Use `/color set` to pick one!",
                    color=get_embed_color(interaction.user.id)
                )
                embed.set_image(url="attachment://colorimage.png")
                await interaction.followup.send(embed=embed, file=file, ephemeral=False)

        except Exception as e:
            logger.error(f"/color list: {e}", exc_info=True)
            msg = f"Error in `/color list`: `{e}`" if DEBUG else "Something went wrong loading color images."
            await interaction.followup.send(msg, ephemeral=True)

async def setup(bot):
    await bot.add_cog(ColorRoles(bot))
