import io
import discord
from discord.ext import commands
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from utils.logger import get_logger
from utils.constants import GUILD_ID

_logger = get_logger(__name__)


class Logger(commands.Cog):
    """Core logging cog that listens to Discord gateway events and forwards
    structured embed logs to configured channels.

    Channel routing is stored per-guild in the log_config table. Individual
    channels can be excluded from logging via log_excluded_channels.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "data" / "moderation.db"
        self.initialize_db()

    def initialize_db(self):
        """Create log_config and log_excluded_channels tables, and seed default routes."""
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
        c.execute("""
        CREATE TABLE IF NOT EXISTS log_excluded_channels (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, channel_id)
        )
        """)
        # Seed defaults for log types that need a channel from day one.
        # INSERT OR IGNORE so this never overwrites an admin's custom routing.
        MOD_LOG_CHANNEL = 982644273960873994
        for log_type in ("channel_lock", "infraction_modify", "cleanban"):
            c.execute("""
                INSERT OR IGNORE INTO log_config (guild_id, log_type, channel_id)
                VALUES (?, ?, ?)
            """, (GUILD_ID, log_type, MOD_LOG_CHANNEL))
        conn.commit()
        conn.close()

    def is_channel_excluded(self, guild_id: int, channel_id: int) -> bool:
        """Return True if the given channel is excluded from logging."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT 1 FROM log_excluded_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id)
        )
        result = c.fetchone()
        conn.close()
        return result is not None

    def get_log_channel(self, guild_id: int, log_type: str) -> Optional[int]:
        """Return the configured channel ID for a log type, or None if not set."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT channel_id FROM log_config WHERE guild_id = ? AND log_type = ?",
            (guild_id, log_type)
        )
        result = c.fetchone()
        conn.close()
        return result[0] if result else None

    async def send_log(
        self,
        guild_id: int,
        log_type: str,
        embed: discord.Embed,
        source_channel_id: Optional[int] = None
    ):
        """Send a log embed to the channel configured for the given log type.

        Does nothing if the source channel is excluded, the log type has no
        configured channel, or the channel cannot be found.
        """
        if source_channel_id and self.is_channel_excluded(guild_id, source_channel_id):
            return

        channel_id = self.get_log_channel(guild_id, log_type)
        if not channel_id:
            return

        channel = self.bot.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.abc.Messageable):
            return

        try:
            await channel.send(embed=embed)
        except discord.Forbidden as e:
            _logger.error(f"Missing permissions to send log in channel {channel_id}: {e}")
        except Exception as e:
            _logger.error(f"Error sending log: {e}", exc_info=True)

    # ── Message events ────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """Log a single message deletion."""
        if message.author.bot or not message.guild:
            return

        embed = discord.Embed(
            title="Message Deleted",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
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

        await self.send_log(message.guild.id, "message_delete", embed, message.channel.id)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        """Log a bulk message deletion, showing a sample of the affected messages."""
        if not messages or not messages[0].guild:
            return

        guild = messages[0].guild
        channel = messages[0].channel

        embed = discord.Embed(
            title="Bulk Message Delete",
            description=f"**{len(messages)}** messages deleted in {channel.mention}",
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc)
        )

        # Show up to 5 messages as a preview
        sample = []
        for msg in messages[:5]:
            content = msg.content[:100] if msg.content else "*No content*"
            sample.append(f"**{msg.author}**: {content}")

        if sample:
            embed.add_field(name="Sample Messages", value="\n".join(sample), inline=False)

        if len(messages) > 5:
            embed.add_field(name="Note", value=f"Showing 5 of {len(messages)} deleted messages", inline=False)

        await self.send_log(guild.id, "message_bulk_delete", embed, channel.id)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """Log a message edit (only fires when the content actually changes)."""
        if before.author.bot or not before.guild or before.content == after.content:
            return

        embed = discord.Embed(
            title="Message Edited",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
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

        await self.send_log(before.guild.id, "message_edit", embed, before.channel.id)

    # ── Member events ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Log a member join, including account age and member count."""
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

            await self.send_log(member.guild.id, "member_join", embed)

        except Exception as e:
            error_text = f"⚠️ **Error while logging member join:**\n`{type(e).__name__}: {e}`"
            _logger.error(f"Error logging member join: {e}", exc_info=True)

            # Attempt to report the error to the designated debug channel
            try:
                channel = member.guild.get_channel(1424145004976275617)
                if channel and isinstance(channel, discord.abc.Messageable):
                    await channel.send(error_text)
                else:
                    _logger.error("Could not find error logging channel (1424145004976275617).")
            except Exception as send_err:
                _logger.error(f"Failed to send error message to debug channel: {send_err}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Log a member leave or kick, including their roles and join date."""
        embed = discord.Embed(
            title="Member Left",
            description=f"{member.mention} {member}",
            color=discord.Color.light_gray(),
            timestamp=datetime.now(timezone.utc)
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
        """Log a member ban, fetching the reason from the audit log when possible."""
        embed = discord.Embed(
            title="Member Banned",
            description=f"{user.mention} {user}",
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc)
        )

        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                if entry.target and entry.target.id == user.id:
                    embed.add_field(
                        name="Banned By",
                        value=f"{entry.user.mention} ({entry.user})" if entry.user else "Unknown",
                        inline=False
                    )
                    if entry.reason:
                        embed.add_field(name="Reason", value=entry.reason, inline=False)
                    break
        except discord.Forbidden:
            pass  # Missing audit log access — omit the moderator field

        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"User ID: {user.id}")

        await self.send_log(guild.id, "member_ban", embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        """Log a member unban, fetching the moderator from the audit log when possible."""
        embed = discord.Embed(
            title="Member Unbanned",
            description=f"{user.mention} {user}",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )

        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.unban):
                if entry.target and entry.target.id == user.id:
                    embed.add_field(
                        name="Unbanned By",
                        value=f"{entry.user.mention} ({entry.user})" if entry.user else "Unknown",
                        inline=False
                    )
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
        """Log nickname changes, role additions/removals, and timeout changes."""
        # Nickname change
        if before.nick != after.nick:
            embed = discord.Embed(
                title="Nickname Changed",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Member", value=f"{after.mention} ({after})", inline=False)
            embed.add_field(name="Before", value=before.nick or "*No nickname*", inline=True)
            embed.add_field(name="After", value=after.nick or "*No nickname*", inline=True)
            embed.set_footer(text=f"User ID: {after.id}")

            await self.send_log(after.guild.id, "nickname_change", embed)

        # Role additions and removals
        before_roles = set(before.roles)
        after_roles = set(after.roles)
        added_roles = after_roles - before_roles
        removed_roles = before_roles - after_roles

        if added_roles:
            embed = discord.Embed(
                title="Role Added",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Member", value=f"{after.mention} ({after})", inline=False)
            embed.add_field(name="Roles Added", value=", ".join([r.mention for r in added_roles]), inline=False)
            embed.set_footer(text=f"User ID: {after.id}")

            await self.send_log(after.guild.id, "role_add", embed)

        if removed_roles:
            embed = discord.Embed(
                title="Role Removed",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Member", value=f"{after.mention} ({after})", inline=False)
            embed.add_field(name="Roles Removed", value=", ".join([r.mention for r in removed_roles]), inline=False)
            embed.set_footer(text=f"User ID: {after.id}")

            await self.send_log(after.guild.id, "role_remove", embed)

        # Timeout changes
        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:
                embed = discord.Embed(
                    title="Member Timed Out",
                    color=discord.Color.dark_orange(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(name="Member", value=f"{after.mention} ({after})", inline=False)
                embed.add_field(name="Until", value=f"<t:{int(after.timed_out_until.timestamp())}:F>", inline=False)

                # Try to fetch the moderator who issued the timeout from the audit log
                try:
                    async for entry in after.guild.audit_logs(limit=5, action=discord.AuditLogAction.member_update):
                        if entry.target and entry.target.id == after.id and entry.after.timed_out_until:
                            embed.add_field(
                                name="Timed Out By",
                                value=f"{entry.user.mention} ({entry.user})" if entry.user else "Unknown",
                                inline=False
                            )
                            if entry.reason:
                                embed.add_field(name="Reason", value=entry.reason, inline=False)
                            break
                except discord.Forbidden:
                    pass

                embed.set_footer(text=f"User ID: {after.id}")
                await self.send_log(after.guild.id, "timeout", embed)
            else:
                # Timeout was lifted
                embed = discord.Embed(
                    title="Timeout Removed",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(name="Member", value=f"{after.mention} ({after})", inline=False)
                embed.set_footer(text=f"User ID: {after.id}")
                await self.send_log(after.guild.id, "timeout_remove", embed)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        """Log username or discriminator changes across all guilds the user shares with the bot."""
        if before.name != after.name or before.discriminator != after.discriminator:
            embed = discord.Embed(
                title="Username Changed",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="User", value=f"{after.mention}", inline=False)
            embed.add_field(name="Before", value=str(before), inline=True)
            embed.add_field(name="After", value=str(after), inline=True)
            embed.set_thumbnail(url=after.display_avatar.url)
            embed.set_footer(text=f"User ID: {after.id}")

            # Fan the log out to every guild this user is a member of
            for guild in self.bot.guilds:
                if guild.get_member(after.id):
                    await self.send_log(guild.id, "username_change", embed)

    # ── Voice events ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        """Log voice channel joins, leaves, and moves."""
        if before.channel is None and after.channel is not None:
            # Member joined a voice channel
            embed = discord.Embed(
                title="Voice Channel Join",
                description=f"{member.mention} joined {after.channel.mention}",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text=f"User ID: {member.id}")
            await self.send_log(member.guild.id, "voice_join", embed, after.channel.id)

        elif before.channel is not None and after.channel is None:
            # Member left a voice channel
            embed = discord.Embed(
                title="Voice Channel Leave",
                description=f"{member.mention} left {before.channel.mention}",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text=f"User ID: {member.id}")
            await self.send_log(member.guild.id, "voice_leave", embed, before.channel.id)

        elif (
            before.channel is not None
            and after.channel is not None
            and before.channel != after.channel
        ):
            # Member moved between voice channels
            embed = discord.Embed(
                title="Voice Channel Move",
                description=f"{member.mention} moved from {before.channel.mention} to {after.channel.mention}",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text=f"User ID: {member.id}")
            # Only log the move if neither of the involved channels is excluded
            if not self.is_channel_excluded(member.guild.id, before.channel.id) \
                    and not self.is_channel_excluded(member.guild.id, after.channel.id):
                await self.send_log(member.guild.id, "voice_move", embed)

    # ── Channel / role events ─────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        """Log the creation of a guild channel."""
        embed = discord.Embed(
            title="Channel Created",
            description=f"{channel.mention} (`{channel.name}`)",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Type", value=str(channel.type).title(), inline=True)
        embed.add_field(name="Channel ID", value=channel.id, inline=True)

        await self.send_log(channel.guild.id, "channel_create", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Log the deletion of a guild channel."""
        embed = discord.Embed(
            title="Channel Deleted",
            description=f"`{channel.name}`",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Type", value=str(channel.type).title(), inline=True)
        embed.add_field(name="Channel ID", value=channel.id, inline=True)

        await self.send_log(channel.guild.id, "channel_delete", embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        """Log the creation of a guild role."""
        embed = discord.Embed(
            title="Role Created",
            description=f"{role.mention} (`{role.name}`)",
            color=role.color if role.color != discord.Color.default() else discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Role ID", value=role.id, inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        embed.add_field(name="Hoisted", value="Yes" if role.hoist else "No", inline=True)

        await self.send_log(role.guild.id, "role_create", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        """Log the deletion of a guild role."""
        embed = discord.Embed(
            title="Role Deleted",
            description=f"`{role.name}`",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Role ID", value=role.id, inline=True)

        await self.send_log(role.guild.id, "role_delete", embed)

    # ── Public API for other cogs ─────────────────────────────────────────────

    async def log_moderation_action(
        self,
        guild_id: int,
        action_type: str,
        user: discord.User,
        moderator: discord.User,
        reason: Optional[str] = None,
        duration: Optional[str] = None
    ):
        """Build and send a moderation action embed to the appropriate log channel.

        Called by moderation commands (ban, kick, warn, mute, etc.) after they
        execute their action.

        Parameters
        ----------
        guild_id:
            The guild the action was taken in.
        action_type:
            The action key (e.g. 'ban', 'warn', 'mute'). Controls embed color
            and is used to look up the target log channel.
        user:
            The user the action was taken against.
        moderator:
            The moderator who performed the action.
        reason:
            Optional reason text.
        duration:
            Optional duration string for timed actions like mutes.
        """
        color_map = {
            "warn": discord.Color.yellow(),
            "mute": discord.Color.orange(),
            "unmute": discord.Color.green(),
            "kick": discord.Color.red(),
            "ban": discord.Color.dark_red(),
            "cleanban": discord.Color.dark_red(),
            "unban": discord.Color.green(),
            "timeout": discord.Color.dark_orange(),
            "untimeout": discord.Color.green(),
            "lock": discord.Color.orange(),
            "unlock": discord.Color.green(),
        }

        embed = discord.Embed(
            title=f"Moderation: {action_type.title()}",
            color=color_map.get(action_type, discord.Color.blue()),
            timestamp=datetime.now(timezone.utc)
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

    async def log_ban_messages(
        self,
        guild_id: int,
        user: discord.User,
        deleted_messages: list,
        days: int
    ):
        """Send a text-file attachment to the ban log channel containing all
        messages that were deleted during a cleanban.

        Parameters
        ----------
        guild_id:
            The guild the cleanban occurred in.
        user:
            The banned user.
        deleted_messages:
            List of dicts with keys: channel, channel_id, message_id,
            timestamp, content, attachments.
        days:
            The message history window (in days) that was scanned.
        """
        channel_id = self.get_log_channel(guild_id, "member_ban")
        if not channel_id:
            return
        channel = self.bot.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.abc.Messageable):
            return

        embed = discord.Embed(
            title=f"Cleanban Deleted Messages — {user}",
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="User", value=f"{user.mention} ({user})", inline=False)
        embed.add_field(name="Messages Deleted", value=str(len(deleted_messages)), inline=True)
        embed.add_field(name="Window", value=f"Past {days} day(s)", inline=True)
        embed.set_footer(text=f"User ID: {user.id}")

        if not deleted_messages:
            embed.description = "*No messages found in accessible channels for this time window.*"
            try:
                await channel.send(embed=embed)
            except Exception as e:
                _logger.error(f"Error sending ban message log: {e}")
            return

        # Build a human-readable plaintext log attached as a file
        lines = [
            f"Deleted messages for {user} (ID: {user.id})",
            f"Window: past {days} day(s)",
            f"Total: {len(deleted_messages)} message(s)",
            "=" * 70,
            "",
        ]
        for msg in deleted_messages:
            line = f"[{msg['timestamp']}] #{msg['channel']} (msg {msg['message_id']}): {msg['content']}"
            if msg["attachments"]:
                line += f"\n  Attachments: {', '.join(msg['attachments'])}"
            lines.append(line)

        content = "\n".join(lines)
        file = discord.File(
            io.BytesIO(content.encode("utf-8")),
            filename=f"deleted_messages_{user.id}.txt"
        )

        try:
            await channel.send(embed=embed, file=file)
        except Exception as e:
            _logger.error(f"Error sending ban message log: {e}", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Logger(bot))
