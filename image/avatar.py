import discord
from discord import app_commands
from discord.ext import commands

class Avatar(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="avatar", description="Show your avatar or another user's avatar")
    @app_commands.choices(
        avatar_type=[
            app_commands.Choice(name="Server Avatar", value="server"),
            app_commands.Choice(name="Global Avatar", value="global")
        ]
    )
    async def avatar(self, interaction: discord.Interaction, user: discord.User | discord.Member = None, avatar_type: app_commands.Choice[str] = None):

        target = user or interaction.user
        use_global = avatar_type and avatar_type.value == "global"

        if isinstance(target, discord.Member) and not use_global and target.avatar:
            avatar_url = target.display_avatar.url
            avatar_type = "Server Avatar"
        else:
            avatar_url = target.avatar.url
            avatar_type = "Global Avatar"

        embed = discord.Embed(
            title=f"{target.display_name}'s {avatar_type}",
            color=self.bot.get_cog("EmbedColor").get_user_color(interaction.user)
        )
        embed.set_image(url=avatar_url)
        embed.add_field(name="Direct Link", value=f"[Open Avatar]({avatar_url})")

        await interaction.response.send_message(embed=embed, ephemeral=False)

async def setup(bot):
    await bot.add_cog(Avatar(bot))