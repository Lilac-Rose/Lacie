import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
import os

class RoleTrack(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = os.path.join(os.path.dirname(__file__), 'roletrack.db')
        bot.loop.create_task(self.init_db())
    
    async def init_db(self):
        """Initialize the database tables if they don't exist"""
        async with aiosqlite.connect(self.db_path) as db:
            # Table for tracking opt-in status
            await db.execute('''
                CREATE TABLE IF NOT EXISTS role_tracking_users (
                    user_id INTEGER,
                    guild_id INTEGER,
                    opted_in INTEGER DEFAULT 1,
                    PRIMARY KEY (user_id, guild_id)
                )
            ''')
            
            # Table for storing role data
            await db.execute('''
                CREATE TABLE IF NOT EXISTS tracked_roles (
                    user_id INTEGER,
                    guild_id INTEGER,
                    role_id INTEGER,
                    role_name TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id, role_id)
                )
            ''')
            
            await db.commit()
    
    async def is_opted_in(self, user_id: int, guild_id: int) -> bool:
        """Check if a user is opted into role tracking"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute('''
                SELECT opted_in FROM role_tracking_users 
                WHERE user_id = ? AND guild_id = ?
            ''', (user_id, guild_id)) as cursor:
                result = await cursor.fetchone()
                return result[0] == 1 if result else False
    
    async def save_user_roles(self, member: discord.Member):
        """Save all roles for a user (excluding @everyone)"""
        if not await self.is_opted_in(member.id, member.guild.id):
            return
        
        async with aiosqlite.connect(self.db_path) as db:
            # Clear existing roles for this user in this guild
            await db.execute('''
                DELETE FROM tracked_roles 
                WHERE user_id = ? AND guild_id = ?
            ''', (member.id, member.guild.id))
            
            # Save current roles (excluding @everyone)
            for role in member.roles:
                if role.id != member.guild.id:  # Skip @everyone role
                    await db.execute('''
                        INSERT INTO tracked_roles (user_id, guild_id, role_id, role_name)
                        VALUES (?, ?, ?, ?)
                    ''', (member.id, member.guild.id, role.id, role.name))
            
            await db.commit()
    
    @app_commands.command(name="roletrack", description="Manage role tracking opt-in status")
    @app_commands.describe(
        setting="Choose to opt in or opt out of role tracking"
    )
    @app_commands.choices(setting=[
        app_commands.Choice(name="opt_in", value="opt_in"),
        app_commands.Choice(name="opt_out", value="opt_out")
    ])
    async def roletrack(self, interaction: discord.Interaction, setting: app_commands.Choice[str]):
        """Command to opt in or opt out of role tracking"""
        async with aiosqlite.connect(self.db_path) as db:
            if setting.value == "opt_in":
                # Opt the user in
                await db.execute('''
                    INSERT OR REPLACE INTO role_tracking_users (user_id, guild_id, opted_in)
                    VALUES (?, ?, 1)
                ''', (interaction.user.id, interaction.guild.id))
                
                await db.commit()
                
                # Save current roles (outside the db context)
                await self.save_user_roles(interaction.user)
                
                embed = discord.Embed(
                    title="✅ Role Tracking Enabled",
                    description="You've been opted into role tracking. If you leave and rejoin this server, your roles will be automatically restored.",
                    color=discord.Color.green()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
            elif setting.value == "opt_out":
                # Opt the user out
                await db.execute('''
                    INSERT OR REPLACE INTO role_tracking_users (user_id, guild_id, opted_in)
                    VALUES (?, ?, 0)
                ''', (interaction.user.id, interaction.guild.id))
                
                # Delete their tracked roles
                await db.execute('''
                    DELETE FROM tracked_roles 
                    WHERE user_id = ? AND guild_id = ?
                ''', (interaction.user.id, interaction.guild.id))
                
                await db.commit()
                
                embed = discord.Embed(
                    title="❌ Role Tracking Disabled",
                    description="You've been opted out of role tracking. Your saved roles have been deleted.",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(RoleTrack(bot))