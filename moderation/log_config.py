import discord
from discord.ext import commands
import sqlite3
import os
from .loader import ModerationBase

# All available log types
LOG_TYPES = [
    "message_delete",
    "message_edit",
    "message_bulk_delete",
    "member_join",
    "member_leave",
    "member_ban",
    "member_unban",
    "member_kick",
    "warn",
    "mute",
    "unmute",
    "kick",
    "ban",
    "unban",
    "role_add",
    "role_remove",
    "nickname_change",
    "username_change",
    "timeout",
    "timeout_remove",
    "voice_join",
    "voice_leave",
    "voice_move",
    "channel_create",
    "channel_delete",
    "channel_update",
    "role_create",
    "role_delete",
    "role_update",
    "server_update"
]

class LogConfig(ModerationBase):
    """Commands to configure logging settings"""
    
    @commands.group(name="log", invoke_without_command=True)
    @ModerationBase.is_admin()
    async def log(self, ctx):
        """Logging configuration commands"""
        await ctx.send("Use `!log set`, `!log list`, or `!log remove` to configure logging.")
    
    @log.command(name="set")
    @ModerationBase.is_admin()
    async def log_set(self, ctx, channel: discord.TextChannel, log_type: str):
        """
        Set a log type to a specific channel.
        
        Usage: !log set #channel log_type
        Example: !log set #mod-logs message_delete
        
        Use !log types to see all available log types.
        """
        log_type = log_type.lower()
        
        if log_type not in LOG_TYPES:
            await ctx.send(f"❌ Invalid log type `{log_type}`.\nUse `!log types` to see all available types.")
            return
        
        # Check if bot can send messages in the channel
        permissions = channel.permissions_for(ctx.guild.me)
        if not permissions.send_messages or not permissions.embed_links:
            await ctx.send(f"❌ I don't have permission to send messages and embeds in {channel.mention}!")
            return
        
        # Update database
        self.c.execute("""
            INSERT INTO log_config (guild_id, log_type, channel_id)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, log_type) DO UPDATE SET channel_id = ?
        """, (ctx.guild.id, log_type, channel.id, channel.id))
        self.conn.commit()
        
        await ctx.send(f"✅ Set `{log_type}` logging to {channel.mention}")
    
    @log.command(name="remove")
    @ModerationBase.is_admin()
    async def log_remove(self, ctx, log_type: str):
        """
        Remove a log type configuration.
        
        Usage: !log remove log_type
        Example: !log remove message_delete
        """
        log_type = log_type.lower()
        
        self.c.execute("DELETE FROM log_config WHERE guild_id = ? AND log_type = ?",
                      (ctx.guild.id, log_type))
        
        if self.c.rowcount == 0:
            await ctx.send(f"❌ No logging configured for `{log_type}`.")
        else:
            self.conn.commit()
            await ctx.send(f"✅ Removed `{log_type}` logging.")
    
    @log.command(name="list")
    @ModerationBase.is_admin()
    async def log_list(self, ctx):
        """List all configured logging for this server"""
        self.c.execute("SELECT log_type, channel_id FROM log_config WHERE guild_id = ? ORDER BY log_type",
                      (ctx.guild.id,))
        results = self.c.fetchall()
        
        if not results:
            await ctx.send("❌ No logging configured for this server.\nUse `!log set #channel log_type` to set up logging.")
            return
        
        embed = discord.Embed(
            title=f"Logging Configuration - {ctx.guild.name}",
            color=discord.Color.blue()
        )
        
        # Group by channel
        channel_logs = {}
        for log_type, channel_id in results:
            if channel_id not in channel_logs:
                channel_logs[channel_id] = []
            channel_logs[channel_id].append(log_type)
        
        for channel_id, log_types in channel_logs.items():
            channel = ctx.guild.get_channel(channel_id)
            channel_name = channel.mention if channel else f"Deleted Channel ({channel_id})"
            embed.add_field(
                name=channel_name,
                value=f"```{', '.join(sorted(log_types))}```",
                inline=False
            )
        
        embed.set_footer(text=f"Total: {len(results)} log types configured")
        await ctx.send(embed=embed)
    
    @log.command(name="types")
    async def log_types(self, ctx):
        """Show all available log types"""
        embed = discord.Embed(
            title="Available Log Types",
            description="Use these with `!log set #channel <type>`",
            color=discord.Color.blue()
        )
        
        categories = {
            "Message Events": [
                "message_delete",
                "message_edit",
                "message_bulk_delete"
            ],
            "Member Events": [
                "member_join",
                "member_leave",
                "member_ban",
                "member_unban",
                "nickname_change",
                "username_change"
            ],
            "Moderation Actions": [
                "warn",
                "mute",
                "unmute",
                "kick",
                "ban",
                "unban",
                "timeout",
                "timeout_remove"
            ],
            "Role Events": [
                "role_add",
                "role_remove",
                "role_create",
                "role_delete",
                "role_update"
            ],
            "Voice Events": [
                "voice_join",
                "voice_leave",
                "voice_move"
            ],
            "Channel Events": [
                "channel_create",
                "channel_delete",
                "channel_update"
            ],
            "Server Events": [
                "server_update"
            ]
        }
        
        for category, types in categories.items():
            embed.add_field(
                name=category,
                value=f"```{', '.join(types)}```",
                inline=False
            )
        
        embed.set_footer(text=f"Total: {len(LOG_TYPES)} log types available")
        await ctx.send(embed=embed)
    
    @log.command(name="clear")
    @ModerationBase.is_admin()
    async def log_clear(self, ctx):
        """Remove ALL logging configurations for this server"""
        self.c.execute("SELECT COUNT(*) FROM log_config WHERE guild_id = ?", (ctx.guild.id,))
        count = self.c.fetchone()[0]
        
        if count == 0:
            await ctx.send("❌ No logging configured to clear.")
            return
        
        # Confirmation
        from discord.ui import View, Button
        view = View(timeout=30)
        confirmed = {"value": False}
        
        async def yes_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("You can't confirm this action.", ephemeral=True)
                return
            confirmed["value"] = True
            await interaction.response.edit_message(content="✅ Confirmed.", view=None)
            view.stop()
        
        async def no_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("You can't cancel this action.", ephemeral=True)
                return
            confirmed["value"] = False
            await interaction.response.edit_message(content="❌ Cancelled.", view=None)
            view.stop()
        
        yes_button = Button(label="Yes", style=discord.ButtonStyle.danger)
        no_button = Button(label="No", style=discord.ButtonStyle.secondary)
        yes_button.callback = yes_callback
        no_button.callback = no_callback
        view.add_item(yes_button)
        view.add_item(no_button)
        
        await ctx.send(f"⚠️ Are you sure you want to remove **all {count}** logging configurations?", view=view)
        await view.wait()
        
        if not confirmed["value"]:
            return
        
        self.c.execute("DELETE FROM log_config WHERE guild_id = ?", (ctx.guild.id,))
        self.conn.commit()
        
        await ctx.send(f"✅ Cleared all logging configurations ({count} removed).")

async def setup(bot: commands.Bot):
    await bot.add_cog(LogConfig(bot))