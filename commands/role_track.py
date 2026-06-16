import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
from pathlib import Path
from embed.embed_color import get_embed_color
from utils.logger import get_logger
from typing import Optional

logger = get_logger(__name__)

class RoleTrack(commands.Cog):
    """Cog that automatically saves and restores member roles across leaves and rejoins.

    Role snapshots are stored in roletrack.db with a composite primary key of
    (user_id, guild_id). Role IDs are serialised as a comma-separated string
    in a single TEXT column — simple enough that a join table isn't needed.

    Three event listeners keep the snapshot current:
    - on_member_remove: snapshot on leave.
    - on_member_join: restore from snapshot on rejoin; snapshot if brand new.
    - on_member_update: re-snapshot whenever roles change.

    Two slash commands expose the system to members:
    - /syncroles: force a manual snapshot of current roles.
    - /checkroles: display the currently stored snapshot.
    """

    def __init__(self, bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "data" / "roletrack.db"

    async def cog_load(self):
        """Initialise the database table on cog load."""
        await self.init_db()

    async def init_db(self):
        """Create the tracked_roles table if it doesn't exist."""
        async with aiosqlite.connect(self.db_path) as db:
            # role_ids stored as comma-separated string — simple enough, don't need a join table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS tracked_roles (
                    user_id INTEGER,
                    guild_id INTEGER,
                    role_ids TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id)
                )
            ''')

            await db.commit()

    async def save_user_roles(self, member: discord.Member):
        """Snapshot all roles for a member, excluding @everyone.

        Uses INSERT OR REPLACE so this works for both first-time inserts and
        subsequent updates without needing separate code paths.

        Note: @everyone's role ID equals the guild ID, which is how the filter
        works below.
        """
        # @everyone's id == guild id, so this filters it out
        role_ids = [str(role.id) for role in member.roles if role.id != member.guild.id]
        role_ids_str = ",".join(role_ids) if role_ids else ""

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                INSERT OR REPLACE INTO tracked_roles (user_id, guild_id, role_ids, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ''', (member.id, member.guild.id, role_ids_str))

            await db.commit()

    async def get_saved_roles(self, user_id: int, guild_id: int):
        """Return the list of saved role IDs for a member, or an empty list if none are stored."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute('''
                SELECT role_ids FROM tracked_roles
                WHERE user_id = ? AND guild_id = ?
            ''', (user_id, guild_id)) as cursor:
                result = await cursor.fetchone()
                if result and result[0]:
                    return [int(role_id) for role_id in result[0].split(",")]
                return []

    @app_commands.command(name="syncroles", description="Manually sync your current roles to the role tracking system")
    async def syncroles(self, interaction: discord.Interaction):
        """Force a manual snapshot of the caller's current roles.

        Useful if automatic tracking missed a role assignment, or after an
        admin manually adds roles that the listener didn't fire for.
        """
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
            return

        try:
            await self.save_user_roles(interaction.user)

            role_count = len([r for r in interaction.user.roles if r.id != interaction.guild.id])

            embed = discord.Embed(
                title="✅ Roles Synced",
                description=f"Successfully saved {role_count} role(s) to the tracking system.",
                color=get_embed_color(interaction.user.id)
            )
            embed.add_field(
                name="What does this do?",
                value="If you leave and rejoin this server, your roles will be automatically restored.",
                inline=False
            )

            if role_count > 0:
                roles_list = ", ".join([r.name for r in interaction.user.roles if r.id != interaction.guild.id])
                embed.add_field(
                    name="Your Current Roles",
                    value=roles_list,
                    inline=False
                )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Sync Failed",
                description=f"An error occurred while syncing your roles: {str(e)}",
                color=get_embed_color(interaction.user.id)
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="checkroles", description="Check what roles are saved in the database for you")
    async def checkroles(self, interaction: discord.Interaction):
        """Display the currently stored role snapshot for the caller.

        Shows each role by name where possible; for roles that have since been
        deleted from the server, shows the raw ID so the member can see they
        are stored and won't cause errors on restore.
        """
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild:
            await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
            return

        try:
            saved_role_ids = await self.get_saved_roles(interaction.user.id, interaction.guild.id)

            if not saved_role_ids:
                embed = discord.Embed(
                    title="📋 Saved Roles",
                    description="No roles are currently saved for you in the database.",
                    color=get_embed_color(interaction.user.id)
                )
            else:
                roles = []
                for role_id in saved_role_ids:
                    role = interaction.guild.get_role(role_id)
                    if role:
                        roles.append(f"{role.name} (ID: {role_id})")
                    else:
                        # role was deleted from the server but still in db — show it so they know
                        roles.append(f"Deleted Role (ID: {role_id})")

                embed = discord.Embed(
                    title="📋 Saved Roles",
                    description=f"Found {len(saved_role_ids)} role(s) in the database:",
                    color=get_embed_color(interaction.user.id)
                )
                embed.add_field(
                    name="Roles",
                    value="\n".join(roles) if roles else "None",
                    inline=False
                )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Check Failed",
                description=f"An error occurred: {str(e)}",
                color=get_embed_color(interaction.user.id)
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Snapshot the member's roles when they leave so they can be restored on rejoin."""
        await self.save_user_roles(member)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Restore a returning member's roles, or initialise a snapshot for brand-new members.

        Silently skips roles that no longer exist on the server to avoid errors.
        Sends a DM to notify the member of the restoration; DM failures are
        swallowed since users frequently have DMs disabled.
        """
        saved_role_ids = await self.get_saved_roles(member.id, member.guild.id)

        if not saved_role_ids:
            # brand new member — snapshot their roles (probably just @everyone at this point)
            await self.save_user_roles(member)
            return

        # filter out roles that no longer exist on the server
        roles_to_add = []
        for role_id in saved_role_ids:
            role = member.guild.get_role(role_id)
            if role:
                roles_to_add.append(role)

        if not roles_to_add:
            return  # None of the saved roles exist anymore

        try:
            await member.add_roles(*roles_to_add, reason="Role tracking: Restoring previous roles")
            try:
                embed = discord.Embed(
                    title="🎭 Roles Restored",
                    description=f"Welcome back to **{member.guild.name}**! Your roles have been automatically restored.",
                    color=get_embed_color(member.id)
                )
                embed.add_field(
                    name="Restored Roles",
                    value=", ".join([role.name for role in roles_to_add]),
                    inline=False
                )
                await member.send(embed=embed)
            except Exception:
                # User has DMs disabled, that's fine
                pass

        except discord.Forbidden:
            # Bot doesn't have permission to add roles
            pass
        except Exception as e:
            logger.error(f"Error restoring roles for {member}: {e}")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Re-snapshot roles whenever a member's role list changes.

        Comparing before.roles to after.roles avoids unnecessary DB writes for
        unrelated member updates such as nickname changes.
        """
        # only re-save if roles actually changed
        if before.roles != after.roles:
            await self.save_user_roles(after)

async def setup(bot):
    await bot.add_cog(RoleTrack(bot))
