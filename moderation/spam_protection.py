"""Automatic spam detection and rate-limiting with auto-mute."""
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

MUTE_ROLE_ID = 982702037517090836
STAFF_CHANNEL_ID = 876780367296745493
WHITELISTED_ROLE_ID = 952560403970416722
WHITELISTED_CATEGORY_ID = 876780338599305246

class SpamProtection(commands.Cog):
    """Automatic spam detection and prevention system"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "data" / "moderation.db"
        
        # Track user message patterns
        # user_id -> deque of (timestamp, channel_id, content)
        self.user_messages = defaultdict(lambda: deque(maxlen=50))
        
        # Track users already flagged for spam (to avoid duplicate reports)
        self.flagged_users = set()
        
        # Async queue for processing messages
        self.message_queue = asyncio.Queue()
        
        # Start tasks
        self.cleanup_tracking.start()
        self.check_pending_actions.start()
        self.process_message_queue.start()
        
        self.initialize_db()
    
    def initialize_db(self):
        """Create table for tracking pending spam actions"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS spam_actions (
            message_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            spam_data TEXT NOT NULL
        )
        """)
        conn.commit()
        conn.close()
    
    def cog_unload(self):
        """Cleanup when cog is unloaded"""
        self.cleanup_tracking.cancel()
        self.check_pending_actions.cancel()
        self.process_message_queue.cancel()
    
    @tasks.loop(minutes=5)
    async def cleanup_tracking(self):
        """Periodically clean up old message tracking data"""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=10)
        
        for user_id in list(self.user_messages.keys()):
            messages = self.user_messages[user_id]
            # Remove messages older than 10 seconds
            while messages and messages[0][0] < cutoff:
                messages.popleft()
            
            # Remove user from tracking if no recent messages
            if not messages:
                del self.user_messages[user_id]
        
        # Clear flagged users who haven't messaged recently
        self.flagged_users = {
            uid for uid in self.flagged_users 
            if uid in self.user_messages
        }
    
    @tasks.loop(minutes=1)
    async def check_pending_actions(self):
        """Check for expired spam action prompts and apply default action"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        now = datetime.now(timezone.utc).isoformat()
        c.execute(
            "SELECT message_id, user_id, guild_id, spam_data FROM spam_actions WHERE expires_at <= ?",
            (now,)
        )
        expired = c.fetchall()
        
        for message_id, user_id, guild_id, spam_data in expired:
            # Apply default action: keep mute for 1 day
            await self.apply_default_action(user_id, guild_id, spam_data)
            
            # Remove from pending actions
            c.execute("DELETE FROM spam_actions WHERE message_id = ?", (message_id,))
        
        conn.commit()
        conn.close()
    
    async def apply_default_action(self, user_id: int, guild_id: int, spam_data: str):
        """Apply default action when no staff response within 12 hours"""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        
        member = guild.get_member(user_id)
        if not member:
            return
        
        mute_role = guild.get_role(MUTE_ROLE_ID)
        if not mute_role or mute_role in member.roles:
            return
        
        # Add mute with 1 day duration using the mute system
        try:
            await member.add_roles(mute_role, reason="Spam protection - automatic 1 day mute (no staff action)")
            
            # Log using the mute command's database system
            unmute_time = (datetime.utcnow() + timedelta(days=1)).isoformat()
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
            INSERT OR REPLACE INTO mutes (user_id, guild_id, channel_id, unmute_time) 
            VALUES (?, ?, ?, ?)
            """, (user_id, guild_id, STAFF_CHANNEL_ID, unmute_time))
            conn.commit()
            conn.close()
            
            # Log to logging system
            logger = self.bot.get_cog("Logger")
            if logger:
                await logger.log_moderation_action(
                    guild_id, "mute", member, self.bot.user, 
                    "Spam protection - automatic 1 day mute (no staff response)", "1d"
                )
            
            # Notify staff channel
            staff_channel = guild.get_channel(STAFF_CHANNEL_ID)
            if staff_channel:
                await staff_channel.send(
                    f"⚠️ No action was taken on spam report for {member.mention}. "
                    f"Automatically muted for 1 day."
                )
        except Exception as e:
            logger.error(f"Failed to apply default spam action: {e}", exc_info=True)
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Monitor messages for spam patterns - lightweight initial check"""
        # Ignore bots and DMs
        if message.author.bot or not message.guild:
            return
        
        # Ignore users with whitelisted role
        whitelisted_role = message.guild.get_role(WHITELISTED_ROLE_ID)
        if whitelisted_role and whitelisted_role in message.author.roles:
            return
        
        # Ignore messages in whitelisted category
        if isinstance(message.channel, discord.TextChannel):
            if message.channel.category_id == WHITELISTED_CATEGORY_ID:
                return
        
        # Ignore users with mute role already
        mute_role = message.guild.get_role(MUTE_ROLE_ID)
        if mute_role and mute_role in message.author.roles:
            return
        
        # Ignore already flagged users
        if message.author.id in self.flagged_users:
            return
        
        # Add to async queue for processing (non-blocking)
        await self.message_queue.put(message)
    
    @tasks.loop(seconds=0.1)
    async def process_message_queue(self):
        """Process messages from queue asynchronously"""
        try:
            # Process up to 10 messages per cycle to prevent backlog
            for _ in range(10):
                try:
                    message = self.message_queue.get_nowait()
                    await self._process_message(message)
                except asyncio.QueueEmpty:
                    break
        except Exception as e:
            logger.error(f"Error in message queue processing: {e}", exc_info=True)
    
    async def _process_message(self, message: discord.Message):
        """Actually process the message for spam detection"""
        now = datetime.now(timezone.utc)
        user_id = message.author.id
        
        # Add message to tracking
        self.user_messages[user_id].append((
            now,
            message.channel.id,
            message.content[:100]  # Store first 100 chars
        ))
        
        # Check for spam patterns
        spam_detected = await self.check_spam_patterns(message.author, message.guild)
        
        if spam_detected:
            await self.handle_spam(message.author, message.guild, spam_detected)
    
    async def check_spam_patterns(self, member: discord.Member, guild: discord.Guild):
        """Check if user's message pattern indicates spam"""
        messages = self.user_messages[member.id]
        
        if len(messages) < 2:
            return None
        
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=5)
        
        # Get messages in last 5 seconds
        recent_messages = [msg for msg in messages if msg[0] >= cutoff]
        
        if len(recent_messages) < 2:
            return None
        
        # Pattern 1: 10+ messages in same channel within 5 seconds
        channel_counts = defaultdict(int)
        for _, channel_id, _ in recent_messages:
            channel_counts[channel_id] += 1
        
        for channel_id, count in channel_counts.items():
            if count >= 10:
                channel = guild.get_channel(channel_id)
                return {
                    "type": "same_channel",
                    "count": count,
                    "channel": channel,
                    "messages": [msg for msg in recent_messages if msg[1] == channel_id]
                }
        
        # Pattern 2: Messages in 10+ different channels within 5 seconds
        unique_channels = len(set(msg[1] for msg in recent_messages))
        if unique_channels >= 10:
            channels = {}
            for _, channel_id, content in recent_messages:
                if channel_id not in channels:
                    channels[channel_id] = guild.get_channel(channel_id)
            
            return {
                "type": "multiple_channels",
                "count": len(recent_messages),
                "channel_count": unique_channels,
                "channels": channels,
                "messages": recent_messages
            }
        
        return None
    
    async def handle_spam(self, member: discord.Member, guild: discord.Guild, spam_data: dict):
        """Handle detected spam by muting user and alerting staff"""
        # Mark user as flagged
        self.flagged_users.add(member.id)
        
        # Apply mute role
        mute_role = guild.get_role(MUTE_ROLE_ID)
        if not mute_role:
            logger.error(f"Mute role {MUTE_ROLE_ID} not found in guild {guild.id}")
            return

        try:
            await member.add_roles(mute_role, reason="Automatic spam detection")
        except discord.Forbidden:
            logger.error(f"Missing permissions to mute {member.id}")
            return
        except Exception as e:
            logger.error(f"Failed to mute spammer: {e}", exc_info=True)
            return
        
        # Log the automatic mute action
        logger = self.bot.get_cog("Logger")
        if logger:
            await logger.log_moderation_action(
                guild.id, "mute", member, self.bot.user,
                "Automatic spam detection - pending staff review", "pending"
            )
        
        # Try to DM the user
        try:
            await member.send(
                f"You have been automatically muted in **{guild.name}** for spam detection. "
                f"A staff member will review your case shortly."
            )
        except Exception:
            pass  # Can't DM user
        
        # Create staff alert
        staff_channel = guild.get_channel(STAFF_CHANNEL_ID)
        if not staff_channel:
            logger.error(f"Staff channel {STAFF_CHANNEL_ID} not found")
            return
        
        # Build embed
        embed = discord.Embed(
            title="🚨 Spam Detected - User Auto-Muted",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.add_field(
            name="User",
            value=f"{member.mention} ({member})\nID: {member.id}",
            inline=False
        )
        
        if spam_data["type"] == "same_channel":
            embed.add_field(
                name="Spam Pattern",
                value=f"**{spam_data['count']} messages** in {spam_data['channel'].mention} within 5 seconds",
                inline=False
            )
            
            # Show sample messages
            sample_messages = []
            for timestamp, _, content in spam_data["messages"][:5]:
                time_str = timestamp.strftime("%H:%M:%S UTC")
                content_preview = content[:50] + "..." if len(content) > 50 else content
                sample_messages.append(f"`[{time_str}]` {content_preview}")
            
            if sample_messages:
                embed.add_field(
                    name=f"Sample Messages (showing {len(sample_messages)} of {spam_data['count']})",
                    value="\n".join(sample_messages),
                    inline=False
                )
        
        elif spam_data["type"] == "multiple_channels":
            channel_list = ", ".join([
                ch.mention for ch in list(spam_data["channels"].values())[:10]
            ])
            if spam_data["channel_count"] > 10:
                channel_list += f" and {spam_data['channel_count'] - 10} more..."
            
            embed.add_field(
                name="Spam Pattern",
                value=f"**{spam_data['count']} messages** across **{spam_data['channel_count']} channels** within 5 seconds",
                inline=False
            )
            
            embed.add_field(
                name="Channels",
                value=channel_list,
                inline=False
            )
            
            # Show sample messages with channels
            sample_messages = []
            for timestamp, channel_id, content in spam_data["messages"][:5]:
                time_str = timestamp.strftime("%H:%M:%S UTC")
                channel = spam_data["channels"].get(channel_id)
                channel_name = channel.mention if channel else f"<#{channel_id}>"
                content_preview = content[:30] + "..." if len(content) > 30 else content
                sample_messages.append(f"`[{time_str}]` {channel_name}: {content_preview}")
            
            if sample_messages:
                embed.add_field(
                    name=f"Sample Messages (showing {len(sample_messages)} of {spam_data['count']})",
                    value="\n".join(sample_messages),
                    inline=False
                )
        
        embed.add_field(
            name="Action Taken",
            value="✅ User has been automatically muted\n⏰ If no action is taken in 12 hours, mute will be extended to 1 day",
            inline=False
        )
        
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="Use buttons below to take action")
        
        # Create action buttons
        view = SpamActionView(self.bot, member, guild, spam_data, self.db_path)
        
        try:
            msg = await staff_channel.send(embed=embed, view=view)
            
            # Store pending action in database
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
            c.execute("""
            INSERT INTO spam_actions (message_id, user_id, guild_id, created_at, expires_at, spam_data)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                msg.id,
                member.id,
                guild.id,
                datetime.now(timezone.utc).isoformat(),
                expires_at,
                str(spam_data["type"])  # Store simple identifier
            ))
            conn.commit()
            conn.close()
            
            # Store message ID in view for cleanup
            view.alert_message_id = msg.id
            
        except Exception as e:
            logger.error(f"Failed to send spam alert: {e}", exc_info=True)

class SpamActionView(View):
    """Interactive buttons for staff to handle spam reports"""
    
    def __init__(self, bot: commands.Bot, member: discord.Member, guild: discord.Guild, spam_data: dict, db_path: str):
        super().__init__(timeout=43200)  # 12 hour timeout
        self.bot = bot
        self.member = member
        self.guild = guild
        self.spam_data = spam_data
        self.db_path = db_path
        self.alert_message_id = None
    
    async def _remove_from_pending(self):
        """Remove this action from pending database"""
        if self.alert_message_id:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("DELETE FROM spam_actions WHERE message_id = ?", (self.alert_message_id,))
            conn.commit()
            conn.close()
    
    @discord.ui.button(label="Remove Mute", style=discord.ButtonStyle.green, emoji="✅")
    async def remove_mute_button(self, interaction: discord.Interaction, button: Button):
        """Remove the mute from the user"""
        # Check permissions
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.response.send_message(
                "❌ You don't have permission to take this action.",
                ephemeral=True
            )
            return
        
        # Confirmation
        confirm_view = ConfirmView(interaction.user)
        await interaction.response.send_message(
            f"Are you sure you want to **remove the mute** from {self.member.mention}?",
            view=confirm_view,
            ephemeral=True
        )
        await confirm_view.wait()
        
        if not confirm_view.confirmed:
            return
        
        # Remove mute role
        mute_role = self.guild.get_role(MUTE_ROLE_ID)
        if mute_role and mute_role in self.member.roles:
            try:
                await self.member.remove_roles(mute_role, reason=f"Spam mute removed by {interaction.user}")
                
                # Remove from mutes database
                conn = sqlite3.connect(self.db_path)
                c = conn.cursor()
                c.execute("DELETE FROM mutes WHERE user_id = ? AND guild_id = ?",
                         (self.member.id, self.guild.id))
                conn.commit()
                conn.close()
                
                # Log action
                logger = self.bot.get_cog("Logger")
                if logger:
                    await logger.log_moderation_action(
                        self.guild.id, "unmute", self.member, interaction.user,
                        "Spam report - determined to be false positive"
                    )
                
                await interaction.followup.send(
                    f"✅ Mute removed from {self.member.mention}",
                    ephemeral=True
                )
                
                # Update original message
                embed = interaction.message.embeds[0]
                embed.color = discord.Color.green()
                embed.add_field(
                    name="✅ Resolution",
                    value=f"Mute removed by {interaction.user.mention}",
                    inline=False
                )
                await interaction.message.edit(embed=embed, view=None)
                
                # Remove from pending actions
                await self._remove_from_pending()
                
            except Exception as e:
                await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
        else:
            await interaction.followup.send("User is not currently muted.", ephemeral=True)
    
    @discord.ui.button(label="Keep Mute", style=discord.ButtonStyle.gray, emoji="⏱️")
    async def keep_mute_button(self, interaction: discord.Interaction, button: Button):
        """Keep the mute for 1 day"""
        # Check permissions
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.response.send_message(
                "❌ You don't have permission to take this action.",
                ephemeral=True
            )
            return
        
        # Confirmation
        confirm_view = ConfirmView(interaction.user)
        await interaction.response.send_message(
            f"Are you sure you want to **keep the mute** on {self.member.mention}? This will extend the mute for 1 day.",
            view=confirm_view,
            ephemeral=True
        )
        await confirm_view.wait()
        
        if not confirm_view.confirmed:
            return
        
        # Add 1 day mute to database
        unmute_time = (datetime.utcnow() + timedelta(days=1)).isoformat()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
        INSERT OR REPLACE INTO mutes (user_id, guild_id, channel_id, unmute_time) 
        VALUES (?, ?, ?, ?)
        """, (self.member.id, self.guild.id, STAFF_CHANNEL_ID, unmute_time))
        conn.commit()
        conn.close()
        
        # Log the decision
        logger = self.bot.get_cog("Logger")
        if logger:
            await logger.log_moderation_action(
                self.guild.id, "mute", self.member, interaction.user,
                "Spam confirmed - mute extended for 1 day", "1d"
            )
        
        await interaction.followup.send(
            f"✅ Mute kept on {self.member.mention} for 1 day",
            ephemeral=True
        )
        
        # Update original message
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.orange()
        embed.add_field(
            name="⏱️ Resolution",
            value=f"Mute kept for 1 day by {interaction.user.mention}",
            inline=False
        )
        await interaction.message.edit(embed=embed, view=None)
        
        # Remove from pending actions
        await self._remove_from_pending()
    
    @discord.ui.button(label="Ban User", style=discord.ButtonStyle.red, emoji="🔨")
    async def ban_button(self, interaction: discord.Interaction, button: Button):
        """Ban the user"""
        # Check permissions
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message(
                "❌ You don't have permission to ban members.",
                ephemeral=True
            )
            return
        
        # Confirmation
        confirm_view = ConfirmView(interaction.user)
        await interaction.response.send_message(
            f"Are you sure you want to **ban** {self.member.mention} for spam?",
            view=confirm_view,
            ephemeral=True
        )
        await confirm_view.wait()
        
        if not confirm_view.confirmed:
            return
        
        reason = f"Spam (detected by automatic system, banned by {interaction.user})"
        
        # Try to DM user
        try:
            await self.member.send(
                f"You have been **banned** from **{self.guild.name}** for spam.\n"
                f"Reason: {reason}"
            )
        except Exception:
            pass
        
        # Ban user
        try:
            await self.guild.ban(self.member, reason=reason)
            
            # Log infraction (using ModerationBase system)
            mute_cog = self.bot.get_cog("MuteCommand")
            if mute_cog and hasattr(mute_cog, 'log_infraction'):
                await mute_cog.log_infraction(
                    self.guild.id, self.member.id, interaction.user.id, "ban", reason
                )
            
            # Log to logging system
            logger = self.bot.get_cog("Logger")
            if logger:
                await logger.log_moderation_action(
                    self.guild.id, "ban", self.member, interaction.user, reason
                )
            
            await interaction.followup.send(
                f"✅ {self.member.mention} has been banned.",
                ephemeral=True
            )
            
            # Update original message
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.dark_red()
            embed.add_field(
                name="🔨 Resolution",
                value=f"User banned by {interaction.user.mention}",
                inline=False
            )
            await interaction.message.edit(embed=embed, view=None)
            
            # Remove from pending actions
            await self._remove_from_pending()
            
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to ban: {e}", ephemeral=True)

class ConfirmView(View):
    """Simple confirmation dialog"""
    
    def __init__(self, user: discord.User):
        super().__init__(timeout=30)
        self.user = user
        self.confirmed = False
    
    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "❌ Only the moderator who initiated this action can confirm.",
                ephemeral=True
            )
            return
        
        self.confirmed = True
        await interaction.response.edit_message(content="✅ Confirmed.", view=None)
        self.stop()
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.gray)
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "❌ Only the moderator who initiated this action can cancel.",
                ephemeral=True
            )
            return
        
        self.confirmed = False
        await interaction.response.edit_message(content="❌ Cancelled.", view=None)
        self.stop()

async def setup(bot: commands.Bot):
    await bot.add_cog(SpamProtection(bot))