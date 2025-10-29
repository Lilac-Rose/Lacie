import discord
from discord.ext import commands
import sqlite3
import os
from datetime import datetime, timezone
from typing import Optional
import traceback

class Logger(commands.Cog):
    """Core logging system that listens to Discord events and logs them"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = os.path.join(os.path.dirname(__file__), "moderation.db")
        self.initialize_db()
        # Cache for deleted messages (for bulk delete context)
        self.message_cache = {}
    
    def initialize_db(self):
        """Create log_config table for storing logging settings"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS log_config (
            guild_id INTEGER NOT NULL,
            log_type TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, log_type)
        )
        """)
        conn.commit()
        conn.close()
    
    def get_log_channel(self, guild_id: int, log_type: str) -> Optional[int]:
        """Get the channel ID for a specific log type in a guild"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT channel_id FROM log_config WHERE guild_id = ? AND log_type = ?",
                  (guild_id, log_type))
        result = c.fetchone()
        conn.close()
        print(f"[DEBUG] get_log_channel({guild_id}, {log_type}) -> {result}")
        return result[0] if result else None
    
    async def send_log(self, guild_id: int, log_type: str, embed: discord.Embed):
        """Send a log embed to the configured channel"""
        print(f"[DEBUG] send_log called: guild_id={guild_id}, log_type={log_type}")
        
        channel_id = self.get_log_channel(guild_id, log_type)
        if not channel_id:
            print(f"[DEBUG] No channel configured for {log_type} in guild {guild_id}")
            return
        
        print(f"[DEBUG] Looking for channel {channel_id}")
        channel = self.bot.get_channel(channel_id)
        if not channel:
            print(f"[DEBUG] Channel {channel_id} not found via bot.get_channel")
            return
        
        print(f"[DEBUG] Found channel: {channel.name} ({channel.id})")
        
        try:
            msg = await channel.send(embed=embed)
            print(f"[DEBUG] Successfully sent log message {msg.id} to {channel.name}")
        except discord.Forbidden as e:
            print(f"[ERROR] Missing permissions to send log in channel {channel_id}: {e}")
        except Exception as e:
            print(f"[ERROR] Error sending log: {e}")
            traceback.print_exc()
    
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """Log message deletions"""
        if message.author.bot or not message.guild:
            return
        
        embed = discord.Embed(
            title="Message Deleted",
            color=discord.Color.red(),
            timestamp = datetime.now(timezone.utc)
        )
        embed.add_field(name="Author", value=f"{message.author.mention} ({message.author})", inline=False)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Message ID", value=message.id, inline=True)
        
        content = message.content[:1024] if message.content else "*No text content*"
        embed.add_field(name="Content", value=content, inline=False)
        
        if message.attachments:
            attachment_list = "\n".join([f"[{a.filename}]({a.url})" for a in message.attachments])
            embed.add_field(name="Attachments", value=attachment_list, inline=False)
        
        embed.set_footer(text=f"User ID: {message.author.id}")
        
        await self.send_log(message.guild.id, "message_delete", embed)
    
    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        """Log bulk message deletions"""
        if not messages or not messages[0].guild:
            return
        
        guild = messages[0].guild
        channel = messages[0].channel
        
        embed = discord.Embed(
            title="Bulk Message Delete",
            description=f"**{len(messages)}** messages deleted in {channel.mention}",
            color=discord.Color.dark_red(),
            timestamp = datetime.now(timezone.utc)
        )
        
        # Show sample of deleted messages
        sample = []
        for msg in messages[:5]:  # Show first 5
            content = msg.content[:100] if msg.content else "*No content*"
            sample.append(f"**{msg.author}**: {content}")
        
        if sample:
            embed.add_field(name="Sample Messages", value="\n".join(sample), inline=False)
        
        if len(messages) > 5:
            embed.add_field(name="Note", value=f"Showing 5 of {len(messages)} deleted messages", inline=False)
        
        await self.send_log(guild.id, "message_bulk_delete", embed)
    
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """Log message edits"""
        if before.author.bot or not before.guild or before.content == after.content:
            return
        
        embed = discord.Embed(
            title="Message Edited",
            color=discord.Color.orange(),
            timestamp = datetime.now(timezone.utc)
        )
        embed.add_field(name="Author", value=f"{before.author.mention} ({before.author})", inline=False)
        embed.add_field(name="Channel", value=before.channel.mention, inline=True)
        embed.add_field(name="Message ID", value=before.id, inline=True)
        
        before_content = before.content[:1024] if before.content else "*No text content*"
        after_content = after.content[:1024] if after.content else "*No text content*"
        
        embed.add_field(name="Before", value=before_content, inline=False)
        embed.add_field(name="After", value=after_content, inline=False)
        embed.add_field(name="Jump to Message", value=f"[Click here]({after.jump_url})", inline=False)
        
        embed.set_footer(text=f"User ID: {before.author.id}")
        
        await self.send_log(before.guild.id, "message_edit", embed)
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Log member joins"""
        print(f"[DEBUG] ========================================")
        print(f"[DEBUG] on_member_join triggered!")
        print(f"[DEBUG] Member: {member} ({member.id})")
        print(f"[DEBUG] Guild: {member.guild.name} ({member.guild.id})")
        print(f"[DEBUG] Bot user: {self.bot.user}")
        print(f"[DEBUG] ========================================")
        
        try:
            embed = discord.Embed(
                title="Member Joined",
                description=f"{member.mention} {member}",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            
            account_age = (datetime.now(timezone.utc) - member.created_at).days
            embed.add_field(
                name="Account Created",
                value=f"{member.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n({account_age} days ago)",
                inline=False
            )
            embed.add_field(name="Member Count", value=member.guild.member_count, inline=True)
            
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"User ID: {member.id}")

            print(f"[DEBUG] Embed created successfully")
            print(f"[DEBUG] About to call send_log...")
            
            await self.send_log(member.guild.id, "member_join", embed)
            
            print(f"[DEBUG] send_log completed")

        except Exception as e:
            error_text = f"⚠️ **Error while logging member join:**\n`{type(e).__name__}: {e}`"

            print(f"[ERROR] ========================================")
            print(f"[ERROR] Failed to log member join for {member}")
            print(f"[ERROR] Exception: {type(e).__name__}: {e}")
            print(f"[ERROR] ========================================")
            traceback.print_exc()

            # Attempt to send the error to the designated debug channel
            try:
                channel = member.guild.get_channel(1424145004976275617)
                if channel:
                    await channel.send(error_text)
                    print(f"[DEBUG] Sent error to debug channel")
                else:
                    print("[ERROR] Could not find error logging channel (1424145004976275617).")
            except Exception as send_err:
                print(f"[ERROR] Failed to send error message to debug channel: {send_err}")
    
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Log member leaves/kicks"""
        embed = discord.Embed(
            title="Member Left",
            description=f"{member.mention} {member}",
            color=discord.Color.light_gray(),
            timestamp = datetime.now(timezone.utc)
        )
        
        join_date = member.joined_at.strftime('%Y-%m-%d %H:%M:%S UTC') if member.joined_at else "Unknown"
        embed.add_field(name="Joined Server", value=join_date, inline=False)
        
        roles = [role.mention for role in member.roles if role.name != "@everyone"]
        if roles:
            embed.add_field(name="Roles", value=", ".join(roles), inline=False)
        
        embed.add_field(name="Member Count", value=member.guild.member_count, inline=True)
        
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"User ID: {member.id}")
        
        await self.send_log(member.guild.id, "member_leave", embed)
    
    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        """Log member bans"""
        embed = discord.Embed(
            title="Member Banned",
            description=f"{user.mention} {user}",
            color=discord.Color.dark_red(),
            timestamp = datetime.now(timezone.utc)
        )
        
        # Try to get ban reason from audit log
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    embed.add_field(name="Banned By", value=f"{entry.user.mention} ({entry.user})", inline=False)
                    if entry.reason:
                        embed.add_field(name="Reason", value=entry.reason, inline=False)
                    break
        except discord.Forbidden:
            pass
        
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"User ID: {user.id}")
        
        await self.send_log(guild.id, "member_ban", embed)
    
    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        """Log member unbans"""
        embed = discord.Embed(
            title="Member Unbanned",
            description=f"{user.mention} {user}",
            color=discord.Color.green(),
            timestamp = datetime.now(timezone.utc)
        )
        
        # Try to get unban info from audit log
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.unban):
                if entry.target.id == user.id:
                    embed.add_field(name="Unbanned By", value=f"{entry.user.mention} ({entry.user})", inline=False)
                    if entry.reason:
                        embed.add_field(name="Reason", value=entry.reason, inline=False)
                    break
        except discord.Forbidden:
            pass
        
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"User ID: {user.id}")
        
        await self.send_log(guild.id, "member_unban", embed)
    
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Log nickname changes, role changes, and timeouts"""
        # Nickname change
        if before.nick != after.nick:
            embed = discord.Embed(
                title="Nickname Changed",
                color=discord.Color.blue(),
                timestamp = datetime.now(timezone.utc)
            )
            embed.add_field(name="Member", value=f"{after.mention} ({after})", inline=False)
            embed.add_field(name="Before", value=before.nick or "*No nickname*", inline=True)
            embed.add_field(name="After", value=after.nick or "*No nickname*", inline=True)
            embed.set_footer(text=f"User ID: {after.id}")
            
            await self.send_log(after.guild.id, "nickname_change", embed)
        
        # Role changes
        before_roles = set(before.roles)
        after_roles = set(after.roles)
        
        added_roles = after_roles - before_roles
        removed_roles = before_roles - after_roles
        
        if added_roles:
            embed = discord.Embed(
                title="Role Added",
                color=discord.Color.green(),
                timestamp = datetime.now(timezone.utc)
            )
            embed.add_field(name="Member", value=f"{after.mention} ({after})", inline=False)
            embed.add_field(name="Roles Added", value=", ".join([r.mention for r in added_roles]), inline=False)
            embed.set_footer(text=f"User ID: {after.id}")
            
            await self.send_log(after.guild.id, "role_add", embed)
        
        if removed_roles:
            embed = discord.Embed(
                title="Role Removed",
                color=discord.Color.red(),
                timestamp = datetime.now(timezone.utc)
            )
            embed.add_field(name="Member", value=f"{after.mention} ({after})", inline=False)
            embed.add_field(name="Roles Removed", value=", ".join([r.mention for r in removed_roles]), inline=False)
            embed.set_footer(text=f"User ID: {after.id}")
            
            await self.send_log(after.guild.id, "role_remove", embed)
        
        # Timeout changes
        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:
                # Member was timed out
                embed = discord.Embed(
                    title="Member Timed Out",
                    color=discord.Color.dark_orange(),
                    timestamp = datetime.now(timezone.utc)
                )
                embed.add_field(name="Member", value=f"{after.mention} ({after})", inline=False)
                embed.add_field(name="Until", value=f"<t:{int(after.timed_out_until.timestamp())}:F>", inline=False)
                
                # Try to get timeout reason from audit log
                try:
                    async for entry in after.guild.audit_logs(limit=5, action=discord.AuditLogAction.member_update):
                        if entry.target.id == after.id and entry.after.timed_out_until:
                            embed.add_field(name="Timed Out By", value=f"{entry.user.mention} ({entry.user})", inline=False)
                            if entry.reason:
                                embed.add_field(name="Reason", value=entry.reason, inline=False)
                            break
                except discord.Forbidden:
                    pass
                
                embed.set_footer(text=f"User ID: {after.id}")
                await self.send_log(after.guild.id, "timeout", embed)
            else:
                # Timeout was removed
                embed = discord.Embed(
                    title="Timeout Removed",
                    color=discord.Color.green(),
                    timestamp = datetime.now(timezone.utc)
                )
                embed.add_field(name="Member", value=f"{after.mention} ({after})", inline=False)
                embed.set_footer(text=f"User ID: {after.id}")
                await self.send_log(after.guild.id, "timeout_remove", embed)
    
    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        """Log username changes"""
        if before.name != after.name or before.discriminator != after.discriminator:
            embed = discord.Embed(
                title="Username Changed",
                color=discord.Color.blue(),
                timestamp = datetime.now(timezone.utc)
            )
            embed.add_field(name="User", value=f"{after.mention}", inline=False)
            embed.add_field(name="Before", value=str(before), inline=True)
            embed.add_field(name="After", value=str(after), inline=True)
            embed.set_thumbnail(url=after.display_avatar.url)
            embed.set_footer(text=f"User ID: {after.id}")
            
            # Send to all guilds the user is in
            for guild in self.bot.guilds:
                if guild.get_member(after.id):
                    await self.send_log(guild.id, "username_change", embed)
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Log voice channel activities"""
        # Member joined a voice channel
        if before.channel is None and after.channel is not None:
            embed = discord.Embed(
                title="Voice Channel Join",
                description=f"{member.mention} joined {after.channel.mention}",
                color=discord.Color.green(),
                timestamp = datetime.now(timezone.utc)
            )
            embed.set_footer(text=f"User ID: {member.id}")
            await self.send_log(member.guild.id, "voice_join", embed)
        
        # Member left a voice channel
        elif before.channel is not None and after.channel is None:
            embed = discord.Embed(
                title="Voice Channel Leave",
                description=f"{member.mention} left {before.channel.mention}",
                color=discord.Color.red(),
                timestamp = datetime.now(timezone.utc)
            )
            embed.set_footer(text=f"User ID: {member.id}")
            await self.send_log(member.guild.id, "voice_leave", embed)
        
        # Member moved between voice channels
        elif before.channel is not None and after.channel is not None and before.channel != after.channel:
            embed = discord.Embed(
                title="Voice Channel Move",
                description=f"{member.mention} moved from {before.channel.mention} to {after.channel.mention}",
                color=discord.Color.blue(),
                timestamp = datetime.now(timezone.utc)
            )
            embed.set_footer(text=f"User ID: {member.id}")
            await self.send_log(member.guild.id, "voice_move", embed)
    
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        """Log channel creation"""
        embed = discord.Embed(
            title="Channel Created",
            description=f"{channel.mention} (`{channel.name}`)",
            color=discord.Color.green(),
            timestamp = datetime.now(timezone.utc)
        )
        embed.add_field(name="Type", value=str(channel.type).title(), inline=True)
        embed.add_field(name="Channel ID", value=channel.id, inline=True)
        
        await self.send_log(channel.guild.id, "channel_create", embed)
    
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Log channel deletion"""
        embed = discord.Embed(
            title="Channel Deleted",
            description=f"`{channel.name}`",
            color=discord.Color.red(),
            timestamp = datetime.now(timezone.utc)
        )
        embed.add_field(name="Type", value=str(channel.type).title(), inline=True)
        embed.add_field(name="Channel ID", value=channel.id, inline=True)
        
        await self.send_log(channel.guild.id, "channel_delete", embed)
    
    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        """Log role creation"""
        embed = discord.Embed(
            title="Role Created",
            description=f"{role.mention} (`{role.name}`)",
            color=role.color if role.color != discord.Color.default() else discord.Color.green(),
            timestamp = datetime.now(timezone.utc)
        )
        embed.add_field(name="Role ID", value=role.id, inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        embed.add_field(name="Hoisted", value="Yes" if role.hoist else "No", inline=True)
        
        await self.send_log(role.guild.id, "role_create", embed)
    
    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        """Log role deletion"""
        embed = discord.Embed(
            title="Role Deleted",
            description=f"`{role.name}`",
            color=discord.Color.red(),
            timestamp = datetime.now(timezone.utc)
        )
        embed.add_field(name="Role ID", value=role.id, inline=True)
        
        await self.send_log(role.guild.id, "role_delete", embed)
    
    async def log_moderation_action(self, guild_id: int, action_type: str, user: discord.User, moderator: discord.User, reason: Optional[str] = None, duration: Optional[str] = None):
        """
        Public method to log moderation actions from commands.
        """
        color_map = {
            "warn": discord.Color.yellow(),
            "mute": discord.Color.orange(),
            "unmute": discord.Color.green(),
            "kick": discord.Color.red(),
            "ban": discord.Color.dark_red(),
            "unban": discord.Color.green()
        }
        
        embed = discord.Embed(
            title=f"Moderation: {action_type.title()}",
            color=color_map.get(action_type, discord.Color.blue()),
            timestamp = datetime.now(timezone.utc)
        )
        
        embed.add_field(name="User", value=f"{user.mention} ({user})", inline=False)
        embed.add_field(name="Moderator", value=f"{moderator.mention} ({moderator})", inline=False)
        
        if duration:
            embed.add_field(name="Duration", value=duration, inline=True)
        
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        else:
            embed.add_field(name="Reason", value="*No reason provided*", inline=False)
        
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"User ID: {user.id} | Mod ID: {moderator.id}")
        
        await self.send_log(guild_id, action_type, embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Logger(bot))