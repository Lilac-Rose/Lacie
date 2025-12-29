import discord
from discord.ext import commands
import sqlite3
import os
import asyncio

class RoleTrackEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = os.path.join(os.path.dirname(__file__), '..', 'roletrack.db')
    
    def is_opted_in(self, user_id: int, guild_id: int) -> bool:
        """Check if a user is opted into role tracking"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            SELECT opted_in FROM role_tracking_users 
            WHERE user_id = ? AND guild_id = ?
        ''', (user_id, guild_id))
        
        result = c.fetchone()
        conn.close()
        
        return result[0] == 1 if result else False
    
    def get_tracked_roles(self, user_id: int, guild_id: int):
        """Retrieve tracked roles for a user"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            SELECT role_id, role_name FROM tracked_roles 
            WHERE user_id = ? AND guild_id = ?
        ''', (user_id, guild_id))
        
        roles = c.fetchall()
        conn.close()
        return roles
    
    def save_user_roles(self, member: discord.Member):
        """Save all roles for a user (excluding @everyone)"""
        if not self.is_opted_in(member.id, member.guild.id):
            return
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Clear existing roles for this user in this guild
        c.execute('''
            DELETE FROM tracked_roles 
            WHERE user_id = ? AND guild_id = ?
        ''', (member.id, member.guild.id))
        
        # Save current roles (excluding @everyone)
        for role in member.roles:
            if role.id != member.guild.id:  # Skip @everyone role
                c.execute('''
                    INSERT INTO tracked_roles (user_id, guild_id, role_id, role_name)
                    VALUES (?, ?, ?, ?)
                ''', (member.id, member.guild.id, role.id, role.name))
        
        conn.commit()
        conn.close()
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Restore roles when a tracked user rejoins"""
        if member.bot:
            return
        
        # Check if user is opted in
        if not self.is_opted_in(member.id, member.guild.id):
            return
        
        # Get their tracked roles
        tracked_roles = self.get_tracked_roles(member.id, member.guild.id)
        
        if not tracked_roles:
            return
        
        # Wait a moment for Discord to fully process the join
        await asyncio.sleep(1)
        
        # Restore roles
        roles_to_add = []
        missing_roles = []
        
        for role_id, role_name in tracked_roles:
            role = member.guild.get_role(role_id)
            if role:
                # Check if bot can assign this role (bot's highest role must be higher)
                if role < member.guild.me.top_role and not role.is_default():
                    roles_to_add.append(role)
            else:
                missing_roles.append(role_name)
        
        # Add roles
        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="Role tracking: User rejoined server")
                print(f"Restored {len(roles_to_add)} roles for {member.name} ({member.id})")
            except discord.Forbidden:
                print(f"Failed to restore roles for {member.name}: Missing permissions")
            except discord.HTTPException as e:
                print(f"Failed to restore roles for {member.name}: {e}")
        
        # Log if there were missing roles
        if missing_roles:
            print(f"Could not restore the following roles for {member.name} (roles no longer exist): {', '.join(missing_roles)}")
    
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Update tracked roles when a user's roles change"""
        if after.bot:
            return
        
        # Check if user is opted in
        if not self.is_opted_in(after.id, after.guild.id):
            return
        
        # Check if roles actually changed
        if before.roles == after.roles:
            return
        
        # Save updated roles
        self.save_user_roles(after)
        print(f"Updated tracked roles for {after.name} ({after.id})")
    
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Optional: Log when a tracked user leaves"""
        if member.bot:
            return
        
        if self.is_opted_in(member.id, member.guild.id):
            print(f"Tracked user {member.name} ({member.id}) left the server. Roles are saved for restoration.")

async def setup(bot):
    await bot.add_cog(RoleTrackEvents(bot))