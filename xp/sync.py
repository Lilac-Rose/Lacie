import discord
from discord.ext import commands
from discord import app_commands
from moderation.loader import ModerationBase
from .database import get_db
from .utils import load_config, xp_for_level
from discord.utils import get
import asyncio
from concurrent.futures import ThreadPoolExecutor

class XPSync(commands.Cog):
    """Sync XP role rewards for users."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.executor = ThreadPoolExecutor(max_workers=2)

    async def sync_roles_for_user(self, member: discord.Member) -> tuple[int, list[str]]:
        """
        Sync roles for a member based on their lifetime XP level.
        Returns tuple of (level, list of role names added).
        """
        # Load config fresh
        config = load_config()
        ROLE_REWARDS = {int(k): int(v) for k, v in config["ROLE_REWARDS"].items()}
        
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
        # If user parameter is provided, check if requester is admin
        if user is not None:
            if not await ModerationBase.is_admin().predicate(interaction):
                await interaction.response.send_message("You don't have permission to sync roles for other users.", ephemeral=True)
                return
            target_member = interaction.guild.get_member(user.id)
            if not target_member:
                await interaction.response.send_message("User is not in this server.", ephemeral=True)
                return
        else:
            # Sync for the user who ran the command
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

    def _recalc_worker(self, lifetime: bool, user_id: str = None):
        """Worker function that runs in a separate thread"""
        conn, cur = get_db(lifetime)
        total_updated = 0
        
        if user_id:
            # Single user
            cur.execute("SELECT xp FROM xp WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if row:
                xp = row[0]
                new_level = 0
                while xp >= xp_for_level(new_level + 1):
                    new_level += 1
                cur.execute("UPDATE xp SET level = ? WHERE user_id = ?", (new_level, user_id))
                total_updated += 1
        else:
            # All users - batch process
            cur.execute("SELECT user_id, xp FROM xp")
            rows = cur.fetchall()
            
            updates = []
            for uid, xp in rows:
                new_level = 0
                while xp >= xp_for_level(new_level + 1):
                    new_level += 1
                updates.append((new_level, uid))
                total_updated += 1
            
            # Execute all updates at once
            cur.executemany("UPDATE xp SET level = ? WHERE user_id = ?", updates)
        
        conn.commit()
        conn.close()
        
        return total_updated

    @app_commands.command(name="recalc", description="[Admin] Recalculate levels based on current XP curve")
    @app_commands.describe(
        user="Specific user to recalculate (leave empty for everyone)",
        board_type="Which board to recalculate"
    )
    @app_commands.choices(board_type=[
        app_commands.Choice(name="Lifetime", value="lifetime"),
        app_commands.Choice(name="Annual", value="annual"),
        app_commands.Choice(name="Both", value="both")
    ])
    @ModerationBase.is_admin()
    async def recalc(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
        board_type: app_commands.Choice[str] = None
    ):
        # Respond IMMEDIATELY
        if user:
            await interaction.response.send_message(f"🔄 Recalculating levels for {user.mention}...", ephemeral=True)
        else:
            await interaction.response.send_message("🔄 Starting recalculation for all users... I'll update you when done!")
        
        # NOW do the work in background
        board_value = board_type.value if board_type else "both"
        boards = [True, False] if board_value == "both" else [board_value == "lifetime"]
        user_id = str(user.id) if user else None
        
        async def process():
            try:
                total_updated = 0
                for lifetime in boards:
                    board_name = "Lifetime" if lifetime else "Annual"
                    
                    if not user:  # Only send progress for all users
                        await interaction.followup.send(f"⏳ Processing {board_name} database...")
                    
                    count = await asyncio.get_event_loop().run_in_executor(
                        self.executor, self._recalc_worker, lifetime, user_id
                    )
                    total_updated += count
                    
                    if not user:
                        await interaction.followup.send(f"✅ {board_name} complete: {count} entries updated")
                
                board_text = "Lifetime and Annual" if board_value == "both" else board_value.title()
                if user:
                    await interaction.followup.send(f"✅ Recalculated {board_text} level for {user.mention}")
                else:
                    await interaction.followup.send(
                        f"🎉 All done! Recalculated {board_text} levels for {total_updated} total entries. {interaction.user.mention}"
                    )
            except Exception as e:
                await interaction.followup.send(f"❌ Error during recalculation: {str(e)}")
        
        # Start background task
        self.bot.loop.create_task(process())

async def setup(bot: commands.Bot):
    await bot.add_cog(XPSync(bot))