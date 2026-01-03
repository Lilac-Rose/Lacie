import discord
from discord.ext import commands
import traceback
from .loader import ModerationBase
import os
import sqlite3
import json
import asyncio
from functools import partial


class LockCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = os.path.join(os.path.dirname(__file__), "moderation.db")
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.c = self.conn.cursor()
        self.initialize_db()

    def cog_unload(self):
        """Ensure database connection closes when the cog unloads."""
        self.conn.close()

    def initialize_db(self):
        """Create the locked_channels table if it doesn't exist."""
        self.c.execute("""
        CREATE TABLE IF NOT EXISTS locked_channels (
            channel_id INTEGER PRIMARY KEY,
            overwrites_json TEXT NOT NULL
        )
        """)
        self.conn.commit()

    async def _run_in_executor(self, func, *args):
        """Run a blocking function in a thread pool executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, *args))

    def _store_permissions_sync(self, channel_id, overwrites_data):
        """Synchronous database write operation."""
        overwrites_json = json.dumps(overwrites_data)
        self.c.execute("""
        INSERT OR REPLACE INTO locked_channels 
        (channel_id, overwrites_json)
        VALUES (?, ?)
        """, (channel_id, overwrites_json))
        self.conn.commit()

    async def store_permissions(self, channel):
        """Store all channel permission overwrites in the database as JSON BEFORE locking."""
        overwrites_data = {}
        
        for target, overwrite in channel.overwrites.items():
            allow, deny = overwrite.pair()
            overwrites_data[str(target.id)] = {
                'type': 'role' if isinstance(target, discord.Role) else 'member',
                'name': target.name,
                'allow': allow.value,
                'deny': deny.value
            }
        
        # Run database operation in thread pool
        await self._run_in_executor(self._store_permissions_sync, channel.id, overwrites_data)

    def _get_stored_permissions_sync(self, channel_id):
        """Synchronous database read operation."""
        self.c.execute("""
        SELECT overwrites_json
        FROM locked_channels WHERE channel_id = ?
        """, (channel_id,))
        row = self.c.fetchone()
        
        if not row:
            return None
        
        return json.loads(row['overwrites_json'])

    async def get_stored_permissions(self, channel):
        """Retrieve stored permissions from the database."""
        # Run database operation in thread pool
        overwrites_data = await self._run_in_executor(self._get_stored_permissions_sync, channel.id)
        
        if not overwrites_data:
            return None
        
        restored_overwrites = {}
        
        for target_id, data in overwrites_data.items():
            target_id = int(target_id)
            
            # Get the target (role or member)
            if data['type'] == 'role':
                target = channel.guild.get_role(target_id)
            else:
                target = channel.guild.get_member(target_id)
            
            if target:
                overwrite = discord.PermissionOverwrite.from_pair(
                    discord.Permissions(data['allow']),
                    discord.Permissions(data['deny'])
                )
                restored_overwrites[target] = overwrite
        
        return restored_overwrites

    def _remove_stored_permissions_sync(self, channel_id):
        """Synchronous database delete operation."""
        self.c.execute("DELETE FROM locked_channels WHERE channel_id = ?", (channel_id,))
        self.conn.commit()

    async def remove_stored_permissions(self, channel_id):
        """Remove stored permissions from the database."""
        await self._run_in_executor(self._remove_stored_permissions_sync, channel_id)

    @commands.command(name="checkperms")
    @ModerationBase.is_admin()
    async def checkperms(self, ctx, channel: discord.TextChannel = None):
        """Check what permissions the bot has in a channel."""
        if channel is None:
            channel = ctx.channel
        
        perms = channel.permissions_for(ctx.guild.me)
        bot_top_role = ctx.guild.me.top_role
        
        msg = f"Bot permissions in #{channel.name}:\n"
        msg += f"Manage Channels: {perms.manage_channels}\n"
        msg += f"Manage Roles: {perms.manage_roles}\n"
        msg += f"Administrator: {perms.administrator}\n"
        msg += f"\nBot's highest role: {bot_top_role.name} (position {bot_top_role.position})\n"
        
        # Check role hierarchy for everyone and ritualist roles
        everyone_role = ctx.guild.default_role
        ritual_member_id = 952560403970416722
        ritual_member_role = ctx.guild.get_role(ritual_member_id)
        
        msg += f"\nRole Hierarchy Check:\n"
        msg += f"- everyone position: {everyone_role.position}\n"
        if ritual_member_role:
            msg += f"- Ritual Member role position: {ritual_member_role.position} ({ritual_member_role.name})\n"
            msg += f"- Can bot manage Ritual Member role? {bot_top_role.position > ritual_member_role.position}\n"
        else:
            msg += f"- Ritual Member role (ID: {ritual_member_id}): NOT FOUND\n"
        
        msg += f"\nChannel overwrites:\n"
        for target, overwrite in channel.overwrites.items():
            if len(msg) < 1900:
                allow, deny = overwrite.pair()
                msg += f"- {target.name} (ID: {target.id}, Pos: {target.position if hasattr(target, 'position') else 'N/A'}): Allow={allow.value}, Deny={deny.value}\n"
        
        await ctx.send(msg, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="lock")
    @ModerationBase.is_admin()
    async def lock(self, ctx, channel: discord.TextChannel = None):
        """Lock a channel so only Ritual Members can talk."""
        try:
            if channel is None:
                channel = ctx.channel
            
            perms = channel.permissions_for(ctx.guild.me)
            bot_top_role = ctx.guild.me.top_role
            
            if not perms.manage_roles:
                await ctx.message.add_reaction("❌")
                return await ctx.send(f"I need the 'Manage Roles' permission!", allowed_mentions=discord.AllowedMentions.none())
            
            everyone_role = ctx.guild.default_role
            
            # Get Ritual Member role by ID
            ritual_member_id = 952560403970416722
            ritual_member_role = ctx.guild.get_role(ritual_member_id)
            
            if not ritual_member_role:
                await ctx.message.add_reaction("❌")
                # List available roles to help debug
                role_list = "\n".join([f"- {role.name} (ID: {role.id})" for role in ctx.guild.roles[:10]])
                return await ctx.send(f"Could not find Ritual Member role with ID {ritual_member_id}!\n\nFirst 10 roles in server:\n{role_list}", allowed_mentions=discord.AllowedMentions.none())
            
            # Check role hierarchy - bot's role must be HIGHER than the roles it's trying to modify
            # Note: We don't check 'everyone' since it's always position 0 and manageable
            if bot_top_role.position <= ritual_member_role.position:
                await ctx.message.add_reaction("❌")
                return await ctx.send(f"My role ({bot_top_role.name}) must be HIGHER than {ritual_member_role.name} role to manage permissions!", allowed_mentions=discord.AllowedMentions.none())
            
            # Store ALL original permissions BEFORE making any changes (runs in thread pool)
            await self.store_permissions(channel)
            
            # Try to clear overwrites one by one with error handling
            failed_targets = []
            for target in list(channel.overwrites.keys()):
                try:
                    await channel.set_permissions(target, overwrite=None)
                except discord.Forbidden:
                    failed_targets.append(target.name)
            
            if failed_targets:
                print(f"Warning: Could not clear permissions for: {', '.join(failed_targets)}")
            
            # Deny everyone from talking
            try:
                everyone_overwrite = discord.PermissionOverwrite()
                everyone_overwrite.send_messages = False
                await channel.set_permissions(everyone_role, overwrite=everyone_overwrite, reason=f"Channel locked by {ctx.author}")
            except discord.Forbidden as e:
                await ctx.message.add_reaction("❌")
                return await ctx.send(f"Cannot modify 'everyone' role permissions! Missing permissions.", allowed_mentions=discord.AllowedMentions.none())
            
            # Allow Ritual Member role to talk
            try:
                ritual_member_overwrite = discord.PermissionOverwrite()
                ritual_member_overwrite.send_messages = True
                await channel.set_permissions(ritual_member_role, overwrite=ritual_member_overwrite, reason=f"Channel locked by {ctx.author}")
            except discord.Forbidden as e:
                # If we can't set ritual member, at least try to undo the everyone change
                try:
                    await channel.set_permissions(everyone_role, overwrite=None)
                except:
                    pass
                await ctx.message.add_reaction("❌")
                return await ctx.send(f"Cannot modify {ritual_member_role.name} permissions! My role needs to be higher than that role.", allowed_mentions=discord.AllowedMentions.none())
            
            # React with checkmark
            await ctx.message.add_reaction("✅")
            
            # Try to send in channel
            try:
                await ctx.send(f"#{channel.name} has been locked! Only {ritual_member_role.name} can talk.", allowed_mentions=discord.AllowedMentions.none())
            except:
                pass
                
        except discord.Forbidden as e:
            await ctx.message.add_reaction("❌")
            try:
                await ctx.send(f"Missing permissions! My role needs to be higher than the roles I'm trying to modify.", allowed_mentions=discord.AllowedMentions.none())
            except:
                pass
            traceback.print_exc()
        except Exception as e:
            await ctx.message.add_reaction("❌")
            try:
                await ctx.send(f"Error: {e}", allowed_mentions=discord.AllowedMentions.none())
            except:
                pass
            traceback.print_exc()

    @commands.command(name="unlock")
    @ModerationBase.is_admin()
    async def unlock(self, ctx, channel: discord.TextChannel = None):
        """Unlock a channel."""
        try:
            if channel is None:
                channel = ctx.channel
            
            # Check if we have stored permissions for this channel (runs in thread pool)
            stored_overwrites = await self.get_stored_permissions(channel)
            
            if stored_overwrites is None:
                await ctx.message.add_reaction("❌")
                return await ctx.send("This channel wasn't locked with !lock, so I can't restore its permissions.", allowed_mentions=discord.AllowedMentions.none())
            
            # Clear all current overwrites
            failed_targets = []
            for target in list(channel.overwrites.keys()):
                try:
                    await channel.set_permissions(target, overwrite=None)
                except discord.Forbidden:
                    failed_targets.append(target.name)
            
            # Restore all original overwrites
            restored_count = 0
            for target, overwrite in stored_overwrites.items():
                try:
                    await channel.set_permissions(target, overwrite=overwrite, reason=f"Channel unlocked by {ctx.author}")
                    restored_count += 1
                except discord.Forbidden:
                    failed_targets.append(target.name if hasattr(target, 'name') else str(target.id))
            
            # Remove from database (runs in thread pool)
            await self.remove_stored_permissions(channel.id)
            
            # React with checkmark
            await ctx.message.add_reaction("✅")
            
            # Try to send in channel
            try:
                msg = f"#{channel.name} has been unlocked!"
                if failed_targets:
                    msg += f"\nNote: Could not restore permissions for: {', '.join(failed_targets[:5])}"
                    if len(failed_targets) > 5:
                        msg += f" and {len(failed_targets) - 5} more"
                await ctx.send(msg, allowed_mentions=discord.AllowedMentions.none())
            except:
                pass
                
        except discord.Forbidden as e:
            await ctx.message.add_reaction("❌")
            try:
                await ctx.send(f"Missing permissions! My role needs to be higher than the roles I'm trying to modify.", allowed_mentions=discord.AllowedMentions.none())
            except:
                pass
            traceback.print_exc()
        except Exception as e:
            await ctx.message.add_reaction("❌")
            try:
                await ctx.send(f"Error: {e}", allowed_mentions=discord.AllowedMentions.none())
            except:
                pass
            traceback.print_exc()


async def setup(bot):
    await bot.add_cog(LockCog(bot))