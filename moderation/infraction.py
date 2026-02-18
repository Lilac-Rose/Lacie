"""Infraction logging and retrieval system for moderation actions."""
import discord
from discord.ext import commands, tasks
from .loader import ModerationBase
from datetime import datetime, timedelta
from utils.logger import get_logger

logger = get_logger(__name__)

class InfractionCommand(ModerationBase):

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.approval_channel_id = 1467901790333960377
        self.migrate_existing_infractions()
        self.check_auto_removals.start()

    def cog_unload(self):
        """Stop the background task and close DB when cog unloads."""
        self.check_auto_removals.cancel()
        super().cog_unload()

    def migrate_existing_infractions(self):
        """Add new columns to existing infractions table for auto-removal system."""
        try:
            # Add removed column (0 = active, 1 = removed)
            self.c.execute("ALTER TABLE infractions ADD COLUMN removed INTEGER DEFAULT 0")
        except Exception:
            pass  # Column already exists
        
        try:
            # Add removed_date column
            self.c.execute("ALTER TABLE infractions ADD COLUMN removed_date TEXT")
        except Exception:
            pass
        
        try:
            # Add removed_by column (moderator who approved removal)
            self.c.execute("ALTER TABLE infractions ADD COLUMN removed_by INTEGER")
        except Exception:
            pass
        
        try:
            # Add skip_auto_removal column (1 = staff chose to keep it, skip future checks)
            self.c.execute("ALTER TABLE infractions ADD COLUMN skip_auto_removal INTEGER DEFAULT 0")
        except Exception:
            pass
        
        try:
            # Add pending_approval column (1 = approval request already sent, waiting for staff decision)
            self.c.execute("ALTER TABLE infractions ADD COLUMN pending_approval INTEGER DEFAULT 0")
        except Exception:
            pass
        
        self.conn.commit()

    @tasks.loop(hours=24)
    async def check_auto_removals(self):
        """Background task that runs every 24 hours to check for eligible infraction removals."""
        try:
            self.c.execute("SELECT DISTINCT guild_id FROM infractions WHERE removed=0 AND skip_auto_removal=0 AND pending_approval=0")
            guilds = [row[0] for row in self.c.fetchall()]

            for guild_id in guilds:
                self.c.execute("""
                    SELECT DISTINCT user_id 
                    FROM infractions 
                    WHERE guild_id=? AND removed=0 AND skip_auto_removal=0 AND pending_approval=0
                """, (guild_id,))
                users = [row[0] for row in self.c.fetchall()]

                for user_id in users:
                    await self.check_user_eligibility(guild_id, user_id)

        except Exception as e:
            logger.error(f"Error in auto-removal check: {e}", exc_info=True)

    @check_auto_removals.before_loop
    async def before_check_auto_removals(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()

    async def check_user_eligibility(self, guild_id: int, user_id: int):
        """Check if a user's most recent infraction is eligible for removal."""
        try:
            # Get guild
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return
            
            # Check if user is banned
            try:
                ban = await guild.fetch_ban(discord.Object(id=user_id))
                if ban:
                    return  # User is banned, skip
            except discord.NotFound:
                pass  # User is not banned, continue
            except Exception:
                pass  # Error checking ban, continue anyway
            
            # Check if user is in the server
            member = guild.get_member(user_id)
            if not member:
                return  # User not in server, skip
            
            # Get the most recent ACTIVE infraction for this user (not removed, not skipped, not pending)
            self.c.execute("""
                SELECT id, timestamp, type, reason, moderator_id
                FROM infractions
                WHERE user_id=? AND guild_id=? AND removed=0 AND skip_auto_removal=0 AND pending_approval=0
                ORDER BY timestamp DESC
                LIMIT 1
            """, (user_id, guild_id))
            
            most_recent = self.c.fetchone()
            if not most_recent:
                return  # No active infractions
            
            inf_id, timestamp_str, inf_type, reason, mod_id = most_recent
            infraction_date = datetime.fromisoformat(timestamp_str)
            
            # Check if 4 months have passed
            four_months_ago = datetime.utcnow() - timedelta(days=120)
            if infraction_date > four_months_ago:
                return  # Not eligible yet
            
            # Check if user got ANY infractions after this one
            self.c.execute("""
                SELECT COUNT(*) 
                FROM infractions
                WHERE user_id=? AND guild_id=? AND timestamp > ?
            """, (user_id, guild_id, timestamp_str))
            
            newer_infractions = self.c.fetchone()[0]
            
            if newer_infractions > 0:
                return  # User got infractions after this one, not eligible
            
            # User is eligible! Send to staff for approval
            await self.send_removal_approval(guild_id, user_id, inf_id, inf_type, reason, timestamp_str, mod_id)
            
        except Exception as e:
            logger.error(f"Error checking eligibility for user {user_id} in guild {guild_id}: {e}", exc_info=True)

    async def send_removal_approval(self, guild_id: int, user_id: int, inf_id: int, 
                                    inf_type: str, reason: str, timestamp: str, mod_id: int):
        """Send an infraction removal request to the approval channel."""
        try:
            approval_channel = self.bot.get_channel(self.approval_channel_id)
            if not approval_channel:
                logger.error(f"Approval channel {self.approval_channel_id} not found")
                return
            
            # Get guild, user, and moderator info
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return
            
            try:
                user = await self.bot.fetch_user(user_id)
                user_tag = f"{user.name}#{user.discriminator}"
            except Exception:
                user_tag = f"Unknown User ({user_id})"
            
            try:
                moderator = await self.bot.fetch_user(mod_id)
                mod_tag = f"{moderator.name}#{moderator.discriminator}"
            except Exception:
                mod_tag = f"Unknown Mod ({mod_id})"
            
            # Create approval embed
            embed = discord.Embed(
                title="🔔 Infraction Eligible for Auto-Removal",
                description=f"This user has stayed clean for 4 months. Should this infraction be removed?",
                color=discord.Color.blue()
            )
            embed.add_field(name="Server", value=guild.name, inline=False)
            embed.add_field(name="User", value=user_tag, inline=True)
            embed.add_field(name="Infraction ID", value=str(inf_id), inline=True)
            embed.add_field(name="Type", value=inf_type, inline=True)
            embed.add_field(name="Reason", value=reason or "None", inline=False)
            embed.add_field(name="Original Date", value=timestamp.replace("T", " ")[:19], inline=True)
            embed.add_field(name="Original Moderator", value=mod_tag, inline=True)
            embed.set_footer(text=f"User ID: {user_id} | Guild ID: {guild_id}")
            
            # Create approval view
            view = InfractionRemovalView(self, inf_id, user_id, guild_id, user_tag, inf_type, reason, timestamp)
            
            await approval_channel.send(embed=embed, view=view)
            
            # Mark infraction as pending approval so we don't send duplicate requests
            self.c.execute("""
                UPDATE infractions 
                SET pending_approval=1
                WHERE id=?
            """, (inf_id,))
            self.conn.commit()
            
        except Exception as e:
            logger.error(f"Error sending removal approval: {e}", exc_info=True)

    @commands.command(name="inf")
    @ModerationBase.is_admin()
    async def inf(self, ctx, action: str, *args):
        action = action.lower()

        if action == "search":
            if not args:
                await ctx.send("You must provide a user ID to search.")
                return

            try:
                user_id = int(args[0])
            except ValueError:
                await ctx.send("Invalid user ID.")
                return

            try:
                self.c.execute("""
                    SELECT id, user_id, type, reason, moderator_id, timestamp
                    FROM infractions
                    WHERE user_id=? AND guild_id=? AND removed=0
                    ORDER BY timestamp DESC
                """, (user_id, ctx.guild.id))
                results = self.c.fetchall()
            except Exception as e:
                await ctx.send(f"Database error: {e}")
                return

            if not results:
                await ctx.send("This user has no active infractions.")
                return

        elif action == "search_full":
            if not args:
                await ctx.send("You must provide a user ID to search.")
                return

            try:
                user_id = int(args[0])
            except ValueError:
                await ctx.send("Invalid user ID.")
                return

            try:
                self.c.execute("""
                    SELECT id, user_id, type, reason, moderator_id, timestamp, removed, removed_date
                    FROM infractions
                    WHERE user_id=? AND guild_id=?
                    ORDER BY timestamp DESC
                """, (user_id, ctx.guild.id))
                results = self.c.fetchall()
            except Exception as e:
                await ctx.send(f"Database error: {e}")
                return

            if not results:
                await ctx.send("This user has no infractions.")
                return

            # Build full history rows with status
            ids_to_cache = set(row[1] for row in results) | set(row[4] for row in results)
            user_cache = {u.id: u for u in self.bot.users if u.id in ids_to_cache}

            rows = []
            for row in results:
                try:
                    user = user_cache.get(row[1]) or await self.bot.fetch_user(int(row[1]))
                    moderator = user_cache.get(row[4]) or await self.bot.fetch_user(int(row[4]))
                    user_cache[user.id] = user
                    user_cache[moderator.id] = moderator
                except Exception as e:
                    await ctx.send(f"User fetch error: {e}")
                    return

                user_tag = f"{user.name}#{user.discriminator}"
                mod_tag = f"{moderator.name}#{moderator.discriminator}"
                timestamp = row[5].replace("T", " ")[:19]
                reason = row[3] or "None"
                
                # Check if removed
                is_removed = row[6] if len(row) > 6 else 0
                removed_date = row[7] if len(row) > 7 and row[7] else ""
                
                if is_removed:
                    status = f"Removed ({removed_date.replace('T', ' ')[:19]})" if removed_date else "Removed"
                else:
                    status = "Active"

                rows.append({
                    "id": str(row[0]),
                    "user": user_tag,
                    "moderator": mod_tag,
                    "timestamp": timestamp,
                    "type": row[2],
                    "reason": reason,
                    "status": status
                })

            # Prepare table
            widths = {key: max(len(key), *(len(r[key]) for r in rows)) for key in rows[0].keys()}
            header = " | ".join(f"{key.capitalize():{widths[key]}}" for key in rows[0].keys())
            separator = "-" * len(header)

            # Build pages
            chunk_size = 1800
            pages = []
            current_chunk = [header, separator]
            char_count = len("```md\n") + len(header) + len(separator) + 2

            for r in rows:
                line = " | ".join(f"{r[key]:{widths[key]}}" for key in r.keys())
                line_len = len(line) + 1
                if char_count + line_len > chunk_size:
                    pages.append("```md\n" + "\n".join(current_chunk) + "\n```")
                    current_chunk = [header, separator]
                    char_count = len("```md\n") + len(header) + len(separator) + 2
                current_chunk.append(line)
                char_count += line_len

            if current_chunk:
                pages.append("```md\n" + "\n".join(current_chunk) + "\n```")

            # Pagination with buttons
            class PageView(discord.ui.View):
                def __init__(self, pages):
                    super().__init__(timeout=180)
                    self.pages = pages
                    self.current = 0

                async def update_message(self, interaction):
                    await interaction.response.edit_message(content=self.pages[self.current], view=self)

                @discord.ui.button(label="Previous", style=discord.ButtonStyle.blurple)
                async def previous(self, button: discord.ui.Button, interaction: discord.Interaction):
                    self.current = (self.current - 1) % len(self.pages)
                    await self.update_message(interaction)

                @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
                async def next(self, button: discord.ui.Button, interaction: discord.Interaction):
                    self.current = (self.current + 1) % len(self.pages)
                    await self.update_message(interaction)

            await ctx.send(content=pages[0], view=PageView(pages))
            return

        elif action == "list":
            try:
                self.c.execute("""
                    SELECT id, user_id, type, reason, moderator_id, timestamp
                    FROM infractions
                    WHERE guild_id=? AND removed=0
                    ORDER BY timestamp DESC
                """, (ctx.guild.id,))
                results = self.c.fetchall()
            except Exception as e:
                await ctx.send(f"Database error: {e}")
                return

            if not results:
                await ctx.send("No active infractions found in this server.")
                return

        elif action == "delete":
            if not args:
                await ctx.send("You must provide an infraction ID to delete.")
                return

            try:
                inf_id = int(args[0])
            except ValueError:
                await ctx.send("Invalid infraction ID.")
                return

            # Fetch infraction details before deleting
            self.c.execute("""
                SELECT user_id, type, reason, timestamp
                FROM infractions
                WHERE id=? AND guild_id=?
            """, (inf_id, ctx.guild.id))
            infraction = self.c.fetchone()

            if not infraction:
                await ctx.send(f"Infraction {inf_id} not found.")
                return

            user_id, inf_type, reason, timestamp = infraction

            # Delete the infraction (actually delete it, not just mark as removed)
            self.c.execute("DELETE FROM infractions WHERE id=? AND guild_id=?", (inf_id, ctx.guild.id))
            self.conn.commit()

            # Send DM to the user
            try:
                user = await self.bot.fetch_user(user_id)
                embed = discord.Embed(
                    title="Infraction Removed",
                    description=f"An infraction has been removed from your record in **{ctx.guild.name}**.",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Infraction ID", value=str(inf_id), inline=True)
                embed.add_field(name="Type", value=inf_type, inline=True)
                embed.add_field(name="Original Reason", value=reason or "None", inline=False)
                embed.add_field(name="Original Date", value=timestamp.replace("T", " ")[:19], inline=True)
                embed.add_field(name="Removed By", value=f"{ctx.author.name}#{ctx.author.discriminator}", inline=True)
                embed.set_footer(text=f"Server: {ctx.guild.name}")

                await user.send(embed=embed)
                await ctx.send(f"Infraction {inf_id} deleted and user notified.")
            except discord.Forbidden:
                await ctx.send(f"Infraction {inf_id} deleted, but couldn't DM the user (DMs disabled or blocked).")
            except Exception as e:
                await ctx.send(f"Infraction {inf_id} deleted, but failed to notify user: {e}")

            return

        else:
            await ctx.send("Unknown action. Use search, search_full, list, or delete.")
            return

        # Cache users to avoid repeated API calls (for search and list)
        ids_to_cache = set(row[1] for row in results) | set(row[4] for row in results)
        user_cache = {u.id: u for u in self.bot.users if u.id in ids_to_cache}

        # Build rows
        rows = []
        for row in results:
            try:
                user = user_cache.get(row[1]) or await self.bot.fetch_user(int(row[1]))
                moderator = user_cache.get(row[4]) or await self.bot.fetch_user(int(row[4]))
                user_cache[user.id] = user
                user_cache[moderator.id] = moderator
            except Exception as e:
                await ctx.send(f"User fetch error: {e}")
                return

            user_tag = f"{user.name}#{user.discriminator}"
            mod_tag = f"{moderator.name}#{moderator.discriminator}"
            timestamp = row[5].replace("T", " ")[:19]
            reason = row[3] or "None"

            rows.append({
                "id": str(row[0]),
                "user": user_tag,
                "moderator": mod_tag,
                "timestamp": timestamp,
                "type": row[2],
                "reason": reason
            })

        # Prepare table
        widths = {key: max(len(key), *(len(r[key]) for r in rows)) for key in rows[0].keys()}
        header = " | ".join(f"{key.capitalize():{widths[key]}}" for key in rows[0].keys())
        separator = "-" * len(header)

        # Build pages
        chunk_size = 1800
        pages = []
        current_chunk = [header, separator]
        char_count = len("```md\n") + len(header) + len(separator) + 2

        for r in rows:
            line = " | ".join(f"{r[key]:{widths[key]}}" for key in r.keys())
            line_len = len(line) + 1
            if char_count + line_len > chunk_size:
                pages.append("```md\n" + "\n".join(current_chunk) + "\n```")
                current_chunk = [header, separator]
                char_count = len("```md\n") + len(header) + len(separator) + 2
            current_chunk.append(line)
            char_count += line_len

        if current_chunk:
            pages.append("```md\n" + "\n".join(current_chunk) + "\n```")

        # Pagination with buttons
        class PageView(discord.ui.View):
            def __init__(self, pages):
                super().__init__(timeout=180)
                self.pages = pages
                self.current = 0

            async def update_message(self, interaction):
                await interaction.response.edit_message(content=self.pages[self.current], view=self)

            @discord.ui.button(label="Previous", style=discord.ButtonStyle.blurple)
            async def previous(self, button: discord.ui.Button, interaction: discord.Interaction):
                self.current = (self.current - 1) % len(self.pages)
                await self.update_message(interaction)

            @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
            async def next(self, button: discord.ui.Button, interaction: discord.Interaction):
                self.current = (self.current + 1) % len(self.pages)
                await self.update_message(interaction)

        await ctx.send(content=pages[0], view=PageView(pages))


class InfractionRemovalView(discord.ui.View):
    """View for approving or denying infraction auto-removals."""
    
    def __init__(self, cog, inf_id, user_id, guild_id, user_tag, inf_type, reason, timestamp):
        super().__init__(timeout=None)
        self.cog = cog
        self.inf_id = inf_id
        self.user_id = user_id
        self.guild_id = guild_id
        self.user_tag = user_tag
        self.inf_type = inf_type
        self.reason = reason
        self.timestamp = timestamp
    
    @discord.ui.button(label="Remove Infraction", style=discord.ButtonStyle.green, custom_id="approve_removal")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Approve the removal - mark infraction as removed."""
        try:
            # Mark infraction as removed and clear pending flag
            self.cog.c.execute("""
                UPDATE infractions 
                SET removed=1, removed_date=?, removed_by=?, pending_approval=0
                WHERE id=?
            """, (datetime.utcnow().isoformat(), interaction.user.id, self.inf_id))
            self.cog.conn.commit()
            
            # Update embed
            embed = discord.Embed(
                title="✅ Infraction Removed",
                description="This infraction has been removed from the user's active record.",
                color=discord.Color.green()
            )
            embed.add_field(name="User", value=self.user_tag, inline=True)
            embed.add_field(name="Infraction ID", value=str(self.inf_id), inline=True)
            embed.add_field(name="Type", value=self.inf_type, inline=True)
            embed.add_field(name="Original Date", value=self.timestamp.replace("T", " ")[:19], inline=True)
            embed.add_field(name="Removed By", value=interaction.user.mention, inline=True)
            embed.add_field(name="Removed At", value=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), inline=True)
            
            await interaction.response.edit_message(embed=embed, view=None)
            
            # Notify user
            try:
                user = await self.cog.bot.fetch_user(self.user_id)
                guild = self.cog.bot.get_guild(self.guild_id)
                
                notify_embed = discord.Embed(
                    title="✅ Infraction Removed",
                    description=f"Great news! An infraction has been removed from your record in **{guild.name}** for good behavior.",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                notify_embed.add_field(name="Infraction ID", value=str(self.inf_id), inline=True)
                notify_embed.add_field(name="Type", value=self.inf_type, inline=True)
                notify_embed.add_field(name="Original Reason", value=self.reason or "None", inline=False)
                notify_embed.add_field(name="Original Date", value=self.timestamp.replace("T", " ")[:19], inline=True)
                notify_embed.set_footer(text=f"You stayed clean for 4 months! Keep up the good behavior.")
                
                await user.send(embed=notify_embed)
            except Exception:
                pass  # User has DMs disabled or bot can't reach them
                
        except Exception as e:
            await interaction.response.send_message(f"Error removing infraction: {e}", ephemeral=True)
    
    @discord.ui.button(label="Keep Infraction", style=discord.ButtonStyle.red, custom_id="deny_removal")
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Deny the removal - mark to skip future auto-removal checks."""
        try:
            # Mark infraction to skip future checks and clear pending flag
            self.cog.c.execute("""
                UPDATE infractions 
                SET skip_auto_removal=1, pending_approval=0
                WHERE id=?
            """, (self.inf_id,))
            self.cog.conn.commit()
            
            # Update embed
            embed = discord.Embed(
                title="❌ Removal Denied",
                description="This infraction will remain active and will not be checked for auto-removal again.",
                color=discord.Color.red()
            )
            embed.add_field(name="User", value=self.user_tag, inline=True)
            embed.add_field(name="Infraction ID", value=str(self.inf_id), inline=True)
            embed.add_field(name="Type", value=self.inf_type, inline=True)
            embed.add_field(name="Original Date", value=self.timestamp.replace("T", " ")[:19], inline=True)
            embed.add_field(name="Decision By", value=interaction.user.mention, inline=True)
            embed.add_field(name="Decision At", value=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), inline=True)
            
            await interaction.response.edit_message(embed=embed, view=None)
            
        except Exception as e:
            await interaction.response.send_message(f"Error denying removal: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(InfractionCommand(bot))