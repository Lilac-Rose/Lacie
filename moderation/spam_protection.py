import re
import discord
from discord.ext import commands, tasks
from discord.ui import View, Button
import asyncio
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
import sqlite3
from pathlib import Path
from utils.logger import get_logger

logger = get_logger(__name__)

NOTIFICATIONS_CHANNEL_ID = 1470441786810826884
WHITELISTED_ROLE_ID = 952560403970416722
WHITELISTED_CATEGORY_ID = 876780338599305246

# Thresholds
CROSS_CHANNEL_WINDOW_SECONDS = 10
CROSS_CHANNEL_MIN_CHANNELS = 3
SAME_CHANNEL_WINDOW_SECONDS = 5
SAME_CHANNEL_MIN_MESSAGES = 10

# Discord invite link pattern
INVITE_PATTERN = re.compile(
    r"discord(?:app\.com/invite|\.com/invite|\.gg)/([a-zA-Z0-9\-]+)",
    re.IGNORECASE
)

class SpamProtection(commands.Cog):
    """Automatic spam detection and prevention system"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "data" / "moderation.db"

        # user_id -> deque of (timestamp, channel_id, content)
        self.user_messages = defaultdict(lambda: deque(maxlen=50))

        # Track users already flagged (to avoid duplicate reports)
        self.flagged_users = set()

        self.message_queue = asyncio.Queue()

        self.cleanup_tracking.start()
        self.check_pending_actions.start()
        self.process_message_queue.start()

        self.initialize_db()

    def initialize_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS spam_actions (
            message_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            spam_type TEXT NOT NULL
        )
        """)
        conn.commit()
        conn.close()

    async def cog_unload(self):
        self.cleanup_tracking.cancel()
        self.check_pending_actions.cancel()
        self.process_message_queue.cancel()

    @tasks.loop(minutes=5)
    async def cleanup_tracking(self):
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=max(CROSS_CHANNEL_WINDOW_SECONDS, SAME_CHANNEL_WINDOW_SECONDS))

        for user_id in list(self.user_messages.keys()):
            messages = self.user_messages[user_id]
            while messages and messages[0][0] < cutoff:
                messages.popleft()
            if not messages:
                del self.user_messages[user_id]

        self.flagged_users = {
            uid for uid in self.flagged_users
            if uid in self.user_messages
        }

    @tasks.loop(minutes=1)
    async def check_pending_actions(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        now = datetime.now(timezone.utc).isoformat()
        c.execute(
            "SELECT message_id, user_id, guild_id, spam_type FROM spam_actions WHERE expires_at <= ?",
            (now,)
        )
        expired = c.fetchall()

        for message_id, user_id, guild_id, spam_type in expired:
            await self.apply_default_action(user_id, guild_id, spam_type)
            c.execute("DELETE FROM spam_actions WHERE message_id = ?", (message_id,))

        conn.commit()
        conn.close()

    async def apply_default_action(self, user_id: int, guild_id: int, spam_type: str):
        """Extend timeout to 24 hours when no staff response within 12 hours"""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        member = guild.get_member(user_id)
        if not member:
            return

        try:
            until = datetime.now(timezone.utc) + timedelta(hours=24)
            await member.timeout(until, reason="Spam protection - extended to 24h (no staff action)")

            log_cog = self.bot.get_cog("Logger")
            if log_cog:
                await log_cog.log_moderation_action(
                    guild_id, "timeout", member, self.bot.user,
                    "Spam protection - extended to 24h (no staff response)", "24h"
                )

            notif_channel = guild.get_channel(NOTIFICATIONS_CHANNEL_ID)
            if notif_channel and isinstance(notif_channel, discord.abc.Messageable):
                await notif_channel.send(
                    f"⚠️ No staff action taken on spam report for {member.mention}. "
                    f"Timeout automatically extended to 24 hours."
                )
        except discord.Forbidden:
            logger.error(f"Missing permissions to timeout {user_id}")
        except Exception as e:
            logger.error(f"Failed to apply default spam action: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        whitelisted_role = message.guild.get_role(WHITELISTED_ROLE_ID)
        if whitelisted_role and whitelisted_role in message.author.roles:
            return

        if isinstance(message.channel, discord.TextChannel):
            if message.channel.category_id == WHITELISTED_CATEGORY_ID:
                return

        # Skip if already timed out
        if message.author.timed_out_until and message.author.timed_out_until > datetime.now(timezone.utc):
            return

        if message.author.id in self.flagged_users:
            return

        await self.message_queue.put(message)

    @tasks.loop(seconds=0.1)
    async def process_message_queue(self):
        try:
            for _ in range(10):
                try:
                    message = self.message_queue.get_nowait()
                    await self._process_message(message)
                except asyncio.QueueEmpty:
                    break
        except Exception as e:
            logger.error(f"Error in message queue processing: {e}", exc_info=True)

    async def _process_message(self, message: discord.Message):
        now = datetime.now(timezone.utc)
        user_id = message.author.id

        self.user_messages[user_id].append((
            now,
            message.channel.id,
            message.content[:200]
        ))

        spam_detected = await self.check_spam_patterns(message.author, message.guild, message.content)

        if spam_detected:
            await self.handle_spam(message.author, message.guild, spam_detected)

    async def check_spam_patterns(self, member: discord.Member, guild: discord.Guild, content: str):
        messages = self.user_messages[member.id]

        if not messages:
            return None

        now = datetime.now(timezone.utc)

        # Pattern 1: Invite link sent anywhere
        if INVITE_PATTERN.search(content):
            cross_cutoff = now - timedelta(seconds=CROSS_CHANNEL_WINDOW_SECONDS)
            recent = [msg for msg in messages if msg[0] >= cross_cutoff]
            unique_channels = set(msg[1] for msg in recent)
            channels = {cid: guild.get_channel(cid) for cid in unique_channels}
            return {
                "type": "invite_link",
                "content": content,
                "channel_count": len(unique_channels),
                "channels": channels,
                "messages": recent
            }

        # Pattern 2: Messages in 3+ different channels within 10 seconds
        cross_cutoff = now - timedelta(seconds=CROSS_CHANNEL_WINDOW_SECONDS)
        recent_cross = [msg for msg in messages if msg[0] >= cross_cutoff]
        unique_channels = set(msg[1] for msg in recent_cross)

        if len(unique_channels) >= CROSS_CHANNEL_MIN_CHANNELS:
            channels = {cid: guild.get_channel(cid) for cid in unique_channels}
            return {
                "type": "cross_channel",
                "count": len(recent_cross),
                "channel_count": len(unique_channels),
                "channels": channels,
                "messages": recent_cross
            }

        # Pattern 3: 10+ messages in same channel within 5 seconds
        same_cutoff = now - timedelta(seconds=SAME_CHANNEL_WINDOW_SECONDS)
        recent_same = [msg for msg in messages if msg[0] >= same_cutoff]
        channel_counts = defaultdict(int)
        for _, channel_id, _ in recent_same:
            channel_counts[channel_id] += 1

        for channel_id, count in channel_counts.items():
            if count >= SAME_CHANNEL_MIN_MESSAGES:
                channel = guild.get_channel(channel_id)
                return {
                    "type": "same_channel",
                    "count": count,
                    "channel": channel,
                    "messages": [msg for msg in recent_same if msg[1] == channel_id]
                }

        return None

    async def handle_spam(self, member: discord.Member, guild: discord.Guild, spam_data: dict):
        self.flagged_users.add(member.id)

        # Apply 1-hour timeout
        timeout_until = datetime.now(timezone.utc) + timedelta(hours=1)
        try:
            await member.timeout(timeout_until, reason="Automatic spam detection")
        except discord.Forbidden:
            logger.error(f"Missing permissions to timeout {member.id}")
            return
        except Exception as e:
            logger.error(f"Failed to timeout spammer: {e}", exc_info=True)
            return

        log_cog = self.bot.get_cog("Logger")
        if log_cog:
            await log_cog.log_moderation_action(
                guild.id, "timeout", member, self.bot.user,
                "Automatic spam detection - pending staff review", "1h"
            )

        try:
            await member.send(
                f"You have been automatically timed out in **{guild.name}** for spam detection. "
                f"A staff member will review your case shortly."
            )
        except Exception:
            pass

        notif_channel = guild.get_channel(NOTIFICATIONS_CHANNEL_ID)
        if not notif_channel or not isinstance(notif_channel, discord.abc.Messageable):
            logger.error(f"Notifications channel {NOTIFICATIONS_CHANNEL_ID} not found")
            return

        embed = discord.Embed(
            title="🚨 Spam Detected — User Auto-Timed Out",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )

        embed.add_field(
            name="User",
            value=f"{member.mention} ({member})\nID: `{member.id}`",
            inline=False
        )

        if spam_data["type"] == "invite_link":
            invite_code = INVITE_PATTERN.search(spam_data["content"])
            code_str = f"`{invite_code.group(0)}`" if invite_code else "unknown"
            channel_list = ", ".join(
                ch.mention if ch else f"<#{cid}>"
                for cid, ch in list(spam_data["channels"].items())[:10]
            )
            embed.add_field(
                name="Spam Pattern",
                value=f"**Discord invite link** sent across **{spam_data['channel_count']} channel(s)**\nLink: {code_str}",
                inline=False
            )
            if channel_list:
                embed.add_field(name="Channels", value=channel_list, inline=False)

        elif spam_data["type"] == "cross_channel":
            channel_list = ", ".join(
                ch.mention if ch else f"<#{cid}>"
                for cid, ch in list(spam_data["channels"].items())[:10]
            )
            if spam_data["channel_count"] > 10:
                channel_list += f" and {spam_data['channel_count'] - 10} more..."
            embed.add_field(
                name="Spam Pattern",
                value=f"**{spam_data['count']} messages** across **{spam_data['channel_count']} channels** within {CROSS_CHANNEL_WINDOW_SECONDS}s",
                inline=False
            )
            embed.add_field(name="Channels", value=channel_list, inline=False)

        elif spam_data["type"] == "same_channel":
            ch = spam_data["channel"]
            ch_ref = ch.mention if ch and isinstance(ch, discord.abc.Messageable) else f"<#{spam_data.get('channel_id', '?')}>"
            embed.add_field(
                name="Spam Pattern",
                value=f"**{spam_data['count']} messages** in {ch_ref} within {SAME_CHANNEL_WINDOW_SECONDS}s",
                inline=False
            )

        # Sample messages
        sample_lines = []
        for timestamp, channel_id, content in spam_data["messages"][:5]:
            time_str = timestamp.strftime("%H:%M:%S")
            channel = guild.get_channel(channel_id)
            ch_name = channel.mention if channel else f"<#{channel_id}>"
            preview = content[:50] + "..." if len(content) > 50 else content
            sample_lines.append(f"`[{time_str}]` {ch_name}: {preview}")
        if sample_lines:
            embed.add_field(
                name=f"Sample Messages",
                value="\n".join(sample_lines),
                inline=False
            )

        embed.add_field(
            name="Action Taken",
            value="⏱️ User timed out for **1 hour**\n⚠️ If no action in 12 hours, timeout extends to **24 hours**",
            inline=False
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="Use buttons below to take action")

        view = SpamActionView(self.bot, member, guild, spam_data, self.db_path)

        try:
            msg = await notif_channel.send(embed=embed, view=view)

            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
            c.execute("""
            INSERT INTO spam_actions (message_id, user_id, guild_id, created_at, expires_at, spam_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                msg.id,
                member.id,
                guild.id,
                datetime.now(timezone.utc).isoformat(),
                expires_at,
                spam_data["type"]
            ))
            conn.commit()
            conn.close()

            view.alert_message_id = msg.id

        except Exception as e:
            logger.error(f"Failed to send spam alert: {e}", exc_info=True)


class SpamActionView(View):
    def __init__(self, bot: commands.Bot, member: discord.Member, guild: discord.Guild, spam_data: dict, db_path: str):
        super().__init__(timeout=43200)  # 12 hours
        self.bot = bot
        self.member = member
        self.guild = guild
        self.spam_data = spam_data
        self.db_path = db_path
        self.alert_message_id = None

    async def _remove_from_pending(self):
        if self.alert_message_id:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("DELETE FROM spam_actions WHERE message_id = ?", (self.alert_message_id,))
            conn.commit()
            conn.close()

    def _check_mod(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        return interaction.user.guild_permissions.moderate_members

    @discord.ui.button(label="Undo Timeout", style=discord.ButtonStyle.green, emoji="✅")
    async def undo_timeout_button(self, interaction: discord.Interaction, button: Button):
        if not self._check_mod(interaction):
            await interaction.response.send_message("❌ You don't have permission to do that.", ephemeral=True)
            return

        confirm_view = ConfirmView(interaction.user)
        await interaction.response.send_message(
            f"Remove the timeout from {self.member.mention}?",
            view=confirm_view,
            ephemeral=True
        )
        await confirm_view.wait()
        if not confirm_view.confirmed:
            return

        try:
            await self.member.timeout(None, reason=f"Spam timeout removed by {interaction.user}")

            log_cog = self.bot.get_cog("Logger")
            if log_cog:
                await log_cog.log_moderation_action(
                    self.guild.id, "untimeout", self.member, interaction.user,
                    "Spam report determined to be false positive"
                )

            await interaction.followup.send(f"✅ Timeout removed from {self.member.mention}", ephemeral=True)

            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            embed.add_field(name="✅ Resolution", value=f"Timeout removed by {interaction.user.mention}", inline=False)
            await interaction.message.edit(embed=embed, view=None)
            await self._remove_from_pending()

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @discord.ui.button(label="Extend to 24h", style=discord.ButtonStyle.gray, emoji="⏱️")
    async def extend_timeout_button(self, interaction: discord.Interaction, button: Button):
        if not self._check_mod(interaction):
            await interaction.response.send_message("❌ You don't have permission to do that.", ephemeral=True)
            return

        confirm_view = ConfirmView(interaction.user)
        await interaction.response.send_message(
            f"Extend {self.member.mention}'s timeout to 24 hours?",
            view=confirm_view,
            ephemeral=True
        )
        await confirm_view.wait()
        if not confirm_view.confirmed:
            return

        try:
            until = datetime.now(timezone.utc) + timedelta(hours=24)
            await self.member.timeout(until, reason=f"Spam confirmed — extended by {interaction.user}")

            log_cog = self.bot.get_cog("Logger")
            if log_cog:
                await log_cog.log_moderation_action(
                    self.guild.id, "timeout", self.member, interaction.user,
                    "Spam confirmed — timeout extended to 24h", "24h"
                )

            await interaction.followup.send(f"✅ Timeout extended to 24h for {self.member.mention}", ephemeral=True)

            embed = interaction.message.embeds[0]
            embed.color = discord.Color.orange()
            embed.add_field(name="⏱️ Resolution", value=f"Timeout extended to 24h by {interaction.user.mention}", inline=False)
            await interaction.message.edit(embed=embed, view=None)
            await self._remove_from_pending()

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @discord.ui.button(label="Ban User", style=discord.ButtonStyle.red, emoji="🔨")
    async def ban_button(self, interaction: discord.Interaction, button: Button):
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("❌ You don't have permission to ban members.", ephemeral=True)
            return

        confirm_view = ConfirmView(interaction.user)
        await interaction.response.send_message(
            f"Ban {self.member.mention} for spam?",
            view=confirm_view,
            ephemeral=True
        )
        await confirm_view.wait()
        if not confirm_view.confirmed:
            return

        reason = f"Spam (auto-detected, banned by {interaction.user})"

        try:
            await self.member.send(
                f"You have been **banned** from **{self.guild.name}** for spam.\nReason: {reason}"
            )
        except Exception:
            pass

        try:
            await self.guild.ban(self.member, reason=reason, delete_message_days=1)

            log_cog = self.bot.get_cog("Logger")
            if log_cog:
                await log_cog.log_moderation_action(
                    self.guild.id, "ban", self.member, interaction.user, reason
                )

            await interaction.followup.send(f"✅ {self.member.mention} has been banned.", ephemeral=True)

            embed = interaction.message.embeds[0]
            embed.color = discord.Color.dark_red()
            embed.add_field(name="🔨 Resolution", value=f"User banned by {interaction.user.mention}", inline=False)
            await interaction.message.edit(embed=embed, view=None)
            await self._remove_from_pending()

        except Exception as e:
            await interaction.followup.send(f"❌ Failed to ban: {e}", ephemeral=True)


class ConfirmView(View):
    def __init__(self, user: discord.User):
        super().__init__(timeout=30)
        self.user = user
        self.confirmed = False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ Only the moderator who initiated this can confirm.", ephemeral=True)
            return
        self.confirmed = True
        await interaction.response.edit_message(content="✅ Confirmed.", view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.gray)
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ Only the moderator who initiated this can cancel.", ephemeral=True)
            return
        self.confirmed = False
        await interaction.response.edit_message(content="❌ Cancelled.", view=None)
        self.stop()


async def setup(bot: commands.Bot):
    await bot.add_cog(SpamProtection(bot))
