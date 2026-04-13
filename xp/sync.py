import discord
from discord.ext import commands
from discord import app_commands
from moderation.loader import ModerationBase, ADMIN_ROLE_IDS
from utils.constants import LILAC_ID
from .database import get_db
from .utils import load_config, xp_for_level
from .groups import xp_group, xp_admin_group
from discord.utils import get
import asyncio
from utils.logger import get_logger
from commands.prestige_color import load_color_role_ids, PRESTIGE_ROLES

logger = get_logger(__name__)

class XPSync(commands.Cog):
    """Sync XP role rewards for users."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        xp_group.add_command(app_commands.command(name="sync", description="Sync your XP role rewards.")(self.sync))
        xp_admin_group.add_command(app_commands.command(name="prestige-sync", description="[ADMIN] Sync all members: remove prestige originals where color copies are active.")(self.prestige_sync))

    def check_is_admin(self, user: discord.Member) -> bool:
        """Check if user has admin permissions."""
        is_lilac = user.id == LILAC_ID
        has_admin_role = any(role.id in ADMIN_ROLE_IDS for role in user.roles)
        return has_admin_role or is_lilac

    async def sync_roles_for_user(self, member: discord.Member) -> tuple[int, list[str]]:
        """Sync roles for a member based on their lifetime XP level."""
        config = load_config()
        ROLE_REWARDS = {int(k): int(v) for k, v in config["role_rewards"].items()}

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
                        logger.warning(f"Cannot assign {role.name} to {member} - missing permissions")
                    except discord.HTTPException as e:
                        logger.error(f"HTTP error assigning {role.name} to {member}: {e}")

        return (level, roles_added)

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
                if not isinstance(interaction.user, discord.Member) or not self.check_is_admin(interaction.user):
                    await interaction.response.send_message(
                        "You do not have permission to sync roles for other users.",
                        ephemeral=True
                    )
                    return

            # NOW defer the interaction after permission checks pass
            await interaction.response.defer(ephemeral=False)
            logger.debug(f"Deferred interaction for user {interaction.user.id}")

            if not interaction.guild:
                await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
                return

            # Fetch target member
            try:
                target_member = interaction.guild.get_member(target_user.id)
                if not target_member:
                    logger.debug("Member not in cache, fetching from API")
                    target_member = await interaction.guild.fetch_member(target_user.id)
            except discord.NotFound:
                return await interaction.followup.send(
                    f"{target_user.mention} is not in this server.",
                    ephemeral=True
                )
            except discord.HTTPException as e:
                logger.error(f"HTTP error fetching member: {e}")
                return await interaction.followup.send(
                    f"Error fetching member: {e}",
                    ephemeral=True
                )

            logger.debug(f"Starting role sync for {target_member.id}")
            
            # Sync roles with timeout protection
            try:
                level, roles_added = await asyncio.wait_for(
                    self.sync_roles_for_user(target_member),
                    timeout=25.0  # 25 seconds to stay under Discord's 30s limit
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout during role sync for {target_member.id}")
                return await interaction.followup.send(
                    "Role sync took too long. Please try again or contact an admin.",
                    ephemeral=True
                )

            logger.info(f"Completed sync for {target_member.id}: Level {level}, Roles added: {roles_added}")

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
            logger.warning("Interaction or message not found - may have timed out")
        except Exception as e:
            logger.error(f"Unexpected error in sync command: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    f"Error syncing roles: {str(e)[:100]}",
                    ephemeral=True
                )
            except Exception as followup_error:
                logger.error(f"Could not send error message: {followup_error}")

    @ModerationBase.is_admin()
    async def prestige_sync(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Server only.", ephemeral=True)
            return

        color_ids = load_color_role_ids()
        if not color_ids:
            await interaction.followup.send("No prestige color roles set up yet. Run `/prestige setup` first.", ephemeral=True)
            return

        copy_to_original = {v: guild.get_role(int(k)) for k, v in color_ids.items()}
        all_copy_ids = set(color_ids.values())
        updated = 0

        async for member in guild.fetch_members(limit=None):
            member_copy_ids = [r.id for r in member.roles if r.id in all_copy_ids]
            if not member_copy_ids:
                continue

            to_remove = [
                copy_to_original[cid] for cid in member_copy_ids
                if copy_to_original.get(cid) and copy_to_original[cid] in member.roles
            ]
            if to_remove:
                await member.remove_roles(*to_remove, reason="Prestige color sync: original replaced by color copy")
                updated += 1
                await asyncio.sleep(0.5)

        await interaction.followup.send(f"Sync complete. Updated {updated} member(s).", ephemeral=True)

    async def cog_unload(self):
        xp_group.remove_command("sync")
        xp_admin_group.remove_command("prestige-sync")

async def setup(bot: commands.Bot):
    await bot.add_cog(XPSync(bot))