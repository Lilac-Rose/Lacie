import discord
from discord.ext import commands
from discord import app_commands
from moderation.loader import ModerationBase
from xp.add_xp import get_db
from xp.utils import ROLE_REWARDS
from discord.utils import get

class XPSync(commands.Cog):
    """Sync XP role rewards for users."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def sync_roles_for_user(self, member: discord.Member) -> tuple[int, list[str]]:
        """
        Sync roles for a member based on their lifetime XP level.
        Returns tuple of (llevel, list of role names added).
        """
        conn, cur = get_db(lifetime=True)
        cur.execute("SELECT level FROM xp WHERE user_id = ?", (str(member.id),))
        row = cur.fetchone()
        conn.close()

        if not row:
            return (0, [])
        
        level = row[0]
        roles_added = []

        for lvl, role_id in ROLE_REWARDS.items():
            if level >= lvl:
                role = get(member.guild.roles, id=role_id)
                if role and role not in member.roles:
                    await member.add_roles(role)
                    roles_added.append(role.name)
        
        return (level, roles_added)
    

    @app_commands.command(name="sync", description="Sync your XP role rewards.")
    @app_commands.describe(user="[Admin only] The user to sync roles for.")
    async def sync(
        self,
        interaction: discord.Interaction,
        user: discord.User | None = None,
    ):
        #If user parameter is provided, check if requester is admin
        if user is not None:
            if not await ModerationBase.is_admin().predicate(interaction):
                await interaction.response.send_message("You don't have permission to sync roles for other users.", ephemeral=True)
                return
            target_member = interaction.guild.get_member(user.id)
            if not target_member:
                await interaction.response.send_message("User is not in this server.", ephemeral=True)
                return
        else:
            #Sync for the user who ran the command
            target_member = interaction.user
        
        await interaction.response.defer()

        level, roles_added = await self.sync_roles_for_user(target_member)

        if level == 0:
            await interaction.followup.send(f"{target_member.mention} has no lifetime XP recorded.")
        elif roles_added:
            roles_list = ", ".join(roles_added)
            await interaction.followup.send(
                f"Synced roles for {target_member.mention} (Level {level})\n"
                f"**Roles added:** {roles_list}"
            )
        else:
            await interaction.followup.send(f"{target_member.mention} (Level {level}) already has all eligible role rewards.")

async def setup(bot: commands.Bot):
    await bot.add_cog(XPSync(bot))