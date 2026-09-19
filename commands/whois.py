import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

from moderation.loader import ModerationBase
from embed.embed_color import get_embed_color


class WhoisCommand(commands.Cog):
    """Cog providing the /whois slash command for admin user lookups."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="whois", description="Look up full account/server info for a user by ID or mention")
    @app_commands.describe(user="The user to look up (ID or mention)")
    @ModerationBase.is_admin()
    async def whois(self, interaction: discord.Interaction, user: discord.User):
        """Show account creation date, server join date/tenure, and roles for a user.

        Accepts a raw user ID so staff can look up accounts that have already
        left the server, not just current members.
        """
        await interaction.response.defer()

        member = interaction.guild.get_member(user.id) if interaction.guild else None
        if member is None and interaction.guild:
            try:
                member = await interaction.guild.fetch_member(user.id)
            except discord.NotFound:
                member = None

        embed = discord.Embed(
            title=str(user),
            color=get_embed_color(interaction.user.id),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="ID", value=str(user.id), inline=False)

        created_ts = int(user.created_at.timestamp())
        embed.add_field(
            name="Account Created",
            value=f"<t:{created_ts}:F> (<t:{created_ts}:R>)",
            inline=False,
        )

        if member:
            if member.nick:
                embed.add_field(name="Nickname", value=member.nick, inline=False)

            if member.joined_at:
                joined_ts = int(member.joined_at.timestamp())
                now = datetime.now(timezone.utc)
                delta = now - member.joined_at
                embed.add_field(
                    name="Joined Server",
                    value=f"<t:{joined_ts}:F> (<t:{joined_ts}:R>)",
                    inline=False,
                )
                embed.add_field(
                    name="Time in Server",
                    value=f"{delta.days} days",
                    inline=False,
                )

            roles = [role.mention for role in reversed(member.roles) if role.name != "@everyone"]
            embed.add_field(
                name=f"Roles ({len(roles)})",
                value=", ".join(roles) if roles else "None",
                inline=False,
            )
        else:
            embed.add_field(name="Server Membership", value="Not currently a member of this server", inline=False)

        embed.add_field(name="Bot Account", value="Yes" if user.bot else "No", inline=True)

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(WhoisCommand(bot))
