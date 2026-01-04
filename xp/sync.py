import discord
from discord.ext import commands
from discord import app_commands
from moderation.loader import ModerationBase
from .database import get_db
from .utils import load_config, xp_for_level
from discord.utils import get
import traceback
import asyncio
import os

# Load admin role IDs (same as in moderation base)
ADMIN_ROLE_IDS = {
    int(role_id.strip())
    for role_id in os.getenv("ADMIN_ROLE_IDS", "").split(",")
    if role_id.strip().isdigit()
}
LILAC_ID = 252130669919076352

class XPSync(commands.Cog):
    """Sync XP role rewards for users."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def check_admin_permission(self, user: discord.Member) -> bool:
        """Check if user has admin permissions."""
        # Check if user is Lilac
        if user.id == LILAC_ID:
            return True
        
        # Check if user has admin role
        return any(role.id in ADMIN_ROLE_IDS for role in user.roles)

    async def sync_roles_for_user(self, member: discord.Member) -> tuple[int, list[str]]:
        """Sync roles for a member based on their lifetime XP level."""
        config = load_config()
        ROLE_REWARDS = {int(k): int(v) for k, v in config["ROLE_REWARDS"].items()}

        # Run database operation in executor to avoid blocking
        def get_level():
            conn, cur = get_db("lifetime")
            cur.execute("SELECT level FROM xp WHERE user_id = ?", (str(member.id),))
            row = cur.fetchone()
            conn.close()
            return row

        loop = asyncio.get_event_loop()
        row = await loop.run_in_executor(None, get_level)

        if not row:
            return (0, [])

        level = row[0]
        roles_added = []

        for lvl, role_id in ROLE_REWARDS.items():
            if level >= lvl:
                role = get(member.guild.roles, id=role_id)
                if role and role not in member.roles:
                    # Check bot hierarchy
                    if member.guild.me.top_role <= role:
                        continue
                    try:
                        await member.add_roles(role, reason=f"XP Level {level} role sync")
                        roles_added.append(role.name)
                        # Small delay between role additions to avoid rate limits
                        await asyncio.sleep(0.5)
                    except discord.Forbidden:
                        print(f"Cannot assign {role.name} to {member} - missing permissions")
                    except discord.HTTPException as e:
                        print(f"HTTP error assigning {role.name} to {member}: {e}")

        return (level, roles_added)

    @app_commands.command(name="sync", description="Sync your XP role rewards.")
    @app_commands.describe(user="[Admin only] The user to sync roles for.")
    async def sync(
        self,
        interaction: discord.Interaction,
        user: discord.User | None = None,
    ):
        try:
            # Determine target user
            target_user = user if user else interaction.user
            
            # If syncing someone else, check admin permission BEFORE deferring
            if user and user.id != interaction.user.id:
                # Get the member object for permission checking
                if not isinstance(interaction.user, discord.Member):
                    await interaction.response.send_message(
                        "❌ Cannot verify permissions in DMs.",
                        ephemeral=True
                    )
                    return
                
                # Check admin permissions
                if not self.check_admin_permission(interaction.user):
                    await interaction.response.send_message(
                        "❌ You do not have permission to sync roles for other users.",
                        ephemeral=True
                    )
                    return

            # NOW defer the interaction after permission checks pass
            await interaction.response.defer(ephemeral=False)
            print(f"[SYNC] Deferred interaction for user {interaction.user.id}")

            # Fetch target member
            try:
                target_member = interaction.guild.get_member(target_user.id)
                if not target_member:
                    print(f"[SYNC] Member not in cache, fetching from API")
                    target_member = await interaction.guild.fetch_member(target_user.id)
            except discord.NotFound:
                return await interaction.followup.send(
                    f"{target_user.mention} is not in this server.", 
                    ephemeral=True
                )
            except discord.HTTPException as e:
                print(f"[SYNC] HTTP error fetching member: {e}")
                return await interaction.followup.send(
                    f"Error fetching member: {e}", 
                    ephemeral=True
                )

            print(f"[SYNC] Starting role sync for {target_member.id}")
            
            # Sync roles with timeout protection
            try:
                level, roles_added = await asyncio.wait_for(
                    self.sync_roles_for_user(target_member),
                    timeout=25.0  # 25 seconds to stay under Discord's 30s limit
                )
            except asyncio.TimeoutError:
                print(f"[SYNC] Timeout during role sync for {target_member.id}")
                return await interaction.followup.send(
                    "Role sync took too long. Please try again or contact an admin.", 
                    ephemeral=True
                )

            print(f"[SYNC] Completed sync for {target_member.id}: Level {level}, Roles added: {roles_added}")

            # Send response
            if level == 0:
                await interaction.followup.send(
                    f"{target_member.mention} has no lifetime XP recorded."
                )
            elif roles_added:
                await interaction.followup.send(
                    f"Synced roles for {target_member.mention} (Level {level})\n"
                    f"**Roles added:** {', '.join(roles_added)}"
                )
            else:
                await interaction.followup.send(
                    f"{target_member.mention} (Level {level}) already has all eligible role rewards."
                )
                
        except discord.NotFound:
            print(f"[SYNC] Interaction or message not found - may have timed out")
            # Can't respond if interaction is gone
        except Exception as e:
            print(f"[SYNC] Unexpected error in sync command: {e}")
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    f"Error syncing roles: {str(e)[:100]}", 
                    ephemeral=True
                )
            except Exception as followup_error:
                print(f"[SYNC] Could not send error message: {followup_error}")

async def setup(bot: commands.Bot):
    await bot.add_cog(XPSync(bot))