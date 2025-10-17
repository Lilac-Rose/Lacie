import discord
from discord import app_commands
from discord.ext import commands

class Avatar(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="avatar", description="Show your avatar or another user's avatar")
    async def avatar(self, interaction: discord.Interaction, user: discord.User = None):
        target = user or interaction.user

        embed = discord.Embed(
            title=f"{target.display_name}'s Avatar",
            color=discord.Color.blurple()
        )
        embed.set_image(url=target.display_avatar.url)
        embed.add_field(name="Direct Link", value=f"[Open Avatar]({target.display_avatar.url})")

        await interaction.response.send_message(embed=embed, ephemeral=False)

async def setup(bot):
    await bot.add_cog(Avatar(bot))
