import discord
from discord.ext import commands, tasks
from .loader import ModerationBase
from datetime import datetime, timedelta
from utils.logger import get_logger

logger = get_logger(__name__)


class InfractionCommand(ModerationBase):
    """Cog providing the !inf command for querying and managing infractions.

    Subcommands:
    - ``search <user_id>``       — list active infractions for a user.
    - ``search_full <user_id>``  — full history including removed infractions.
    - ``list``                   — all active infractions in the server.
    - ``delete <id>``            — permanently delete an infraction with notify/silent choice.
    - ``resend <id>``            — re-send the auto-removal approval embed for an infraction.

    Also manages an automatic infraction removal pipeline: every 24 hours,
    users whose most recent infraction is 4+ months old and who have stayed
    in the server without re-offending are sent to an approval channel for
    staff review. Persistent views are re-registered on restart via cog_load.
    """

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        # Channel where auto-removal approval embeds are sent for staff review
        self.approval_channel_id = 1467901790333960377
        self.migrate_existing_infractions()
        self.check_auto_removals.start()

    async def cog_unload(self):
        """Stop the background task and close DB when cog unloads."""
        self.check_auto_removals.cancel()
        await super().cog_unload()

    async def cog_load(self):
        """Re-register persistent views for all pending approval messages.

        Called automatically by discord.py when the cog loads. Queries the DB
        for infractions that were already sent to the approval channel so their
        buttons remain functional after a bot restart.
        """
        self.c.execute("""
            SELECT id, user_id, guild_id, type, reason, timestamp, moderator_id, approval_message_id
            FROM infractions
            WHERE pending_approval=1 AND approval_message_id IS NOT NULL
        """)
        for row in self.c.fetchall():
            inf_id, user_id, guild_id, inf_type, reason, timestamp, mod_id, msg_id = row
            try:
                user = await self.bot.fetch_user(user_id)
                user_tag = f"{user.name}#{user.discriminator}"
            except Exception:
                user_tag = f"Unknown User ({user_id})"
            view = InfractionRemovalView(self, inf_id, user_id, guild_id, user_tag, inf_type, reason, timestamp)
            self.bot.add_view(view, message_id=msg_id)

    def migrate_existing_infractions(self):
        """Add new columns to existing infractions table for auto-removal system.

        Uses ALTER TABLE ... ADD COLUMN and silently catches errors for columns
        that already exist, making this safe to run on every startup.
        """
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

        try:
            # Add approval_message_id column so views can be re-registered after restarts
            self.c.execute("ALTER TABLE infractions ADD COLUMN approval_message_id INTEGER")
        except Exception:
            pass

        self.conn.commit()

    @tasks.loop(hours=24)
    async def check_auto_removals(self):
        """Background task that runs every 24 hours to check for eligible infraction removals.

        Iterates every guild and user with active infractions. For each user,
        delegates to check_user_eligibility which applies the 4-month rule.
        """
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
        """Check if a user's most recent infraction is eligible for auto-removal.

        Eligibility criteria (all must be true):
        - User is not banned.
        - User is currently in the server.
        - Most recent infraction is more than 4 months (120 days) old.
        - User has not left and rejoined since the infraction (clock resets on rejoin).
        - User has no newer infractions of any kind.

        Parameters
        ----------
        guild_id:
            Guild to check eligibility within.
        user_id:
            User to check.
        """
        try:
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

            # Check that the user hasn't left and rejoined since the infraction.
            # If joined_at is after the infraction date, they left and came back — clock resets.
            joined_at = member.joined_at
            if joined_at:
                joined_naive = joined_at.replace(tzinfo=None)
                if joined_naive > infraction_date:
                    return  # Left and rejoined after infraction, not eligible

            # Check if user got ANY infractions after this one
            self.c.execute("""
                SELECT COUNT(*)
                FROM infractions
                WHERE user_id=? AND guild_id=? AND timestamp > ?
            """, (user_id, guild_id, timestamp_str))

            newer_infractions = self.c.fetchone()[0]

            if newer_infractions > 0:
                return  # User got infractions after this one, not eligible

            # User is eligible — send to staff for approval
            await self.send_removal_approval(guild_id, user_id, inf_id, inf_type, reason, timestamp_str, mod_id)

        except Exception as e:
            logger.error(f"Error checking eligibility for user {user_id} in guild {guild_id}: {e}", exc_info=True)

    async def send_removal_approval(self, guild_id: int, user_id: int, inf_id: int,
                                    inf_type: str, reason: str, timestamp: str, mod_id: int):
        """Send an infraction removal request to the approval channel.

        Also marks the infraction as pending_approval and stores the alert
        message ID so the view can be re-registered on the next restart.

        Parameters
        ----------
        guild_id, user_id, inf_id, inf_type, reason, timestamp, mod_id:
            Infraction details used to build the approval embed.
        """
        try:
            approval_channel = self.bot.get_channel(self.approval_channel_id)
            if not approval_channel or not isinstance(approval_channel, discord.abc.Messageable):
                logger.error(f"Approval channel {self.approval_channel_id} not found")
                return

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

            view = InfractionRemovalView(self, inf_id, user_id, guild_id, user_tag, inf_type, reason, timestamp)

            msg = await approval_channel.send(embed=embed, view=view)

            # Mark infraction as pending and store message ID for view re-registration on restart
            self.c.execute("""
                UPDATE infractions
                SET pending_approval=1, approval_message_id=?
                WHERE id=?
            """, (msg.id, inf_id))
            self.conn.commit()

        except Exception as e:
            logger.error(f"Error sending removal approval: {e}", exc_info=True)

    @commands.command(name="inf")
    @ModerationBase.is_admin()
    async def inf(self, ctx, action: str, *args):
        """Query and manage infraction records.

        Parameters
        ----------
        action:
            One of: ``search``, ``search_full``, ``list``, ``delete``, ``resend``.
        args:
            Additional arguments depending on the action (user_id or infraction_id).
        """
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
                async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
                    self.current = (self.current - 1) % len(self.pages)
                    await self.update_message(interaction)

                @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
                async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
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

            embed = discord.Embed(
                title="Delete Infraction?",
                description="Choose how to handle the deletion:",
                color=discord.Color.orange()
            )
            embed.add_field(name="Infraction ID", value=str(inf_id), inline=True)
            embed.add_field(name="Type", value=inf_type, inline=True)
            embed.add_field(name="Reason", value=reason or "None", inline=False)
            embed.add_field(name="Date", value=timestamp.replace("T", " ")[:19], inline=True)
            embed.add_field(name="User ID", value=str(user_id), inline=True)

            view = InfractionDeleteView(self, inf_id, user_id, inf_type, reason, timestamp, ctx.guild)
            await ctx.send(embed=embed, view=view)
            return

        elif action == "resend":
            if not args:
                await ctx.send("You must provide an infraction ID to resend the approval embed for.")
                return

            try:
                inf_id = int(args[0])
            except ValueError:
                await ctx.send("Invalid infraction ID.")
                return

            self.c.execute("""
                SELECT user_id, guild_id, type, reason, timestamp, moderator_id, pending_approval
                FROM infractions
                WHERE id=? AND guild_id=?
            """, (inf_id, ctx.guild.id))
            row = self.c.fetchone()

            if not row:
                await ctx.send(f"Infraction {inf_id} not found.")
                return

            user_id, guild_id, inf_type, reason, timestamp, mod_id, pending = row

            # Clear pending flag and message ID so send_removal_approval runs fresh
            self.c.execute("""
                UPDATE infractions SET pending_approval=0, approval_message_id=NULL WHERE id=?
            """, (inf_id,))
            self.conn.commit()

            await self.send_removal_approval(guild_id, user_id, inf_id, inf_type, reason, timestamp, mod_id)
            await ctx.send(f"Re-sent approval embed for infraction {inf_id}. Delete the old one.")
            return

        else:
            await ctx.send("Unknown action. Use search, search_full, list, delete, or resend.")
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
            async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.current = (self.current - 1) % len(self.pages)
                await self.update_message(interaction)

            @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
            async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.current = (self.current + 1) % len(self.pages)
                await self.update_message(interaction)

        await ctx.send(content=pages[0], view=PageView(pages))


class InfractionDeleteView(discord.ui.View):
    """Confirmation view for manually deleting an infraction, with notify/silent options."""

    def __init__(self, cog, inf_id, user_id, inf_type, reason, timestamp, guild):
        super().__init__(timeout=60)
        self.cog = cog
        self.inf_id = inf_id
        self.user_id = user_id
        self.inf_type = inf_type
        self.reason = reason
        self.timestamp = timestamp
        self.guild = guild

    async def _do_delete(self, interaction: discord.Interaction, notify: bool):
        """Perform the deletion, optionally DM-ing the user, and log to the mod audit trail.

        Parameters
        ----------
        notify:
            If True, attempt to send the user a DM with infraction details.
        """
        try:
            self.cog.c.execute("DELETE FROM infractions WHERE id=? AND guild_id=?", (self.inf_id, self.guild.id))
            self.cog.conn.commit()
        except Exception as e:
            await interaction.response.edit_message(content=f"Database error: {e}", embed=None, view=None)
            return

        if notify:
            try:
                user = await self.cog.bot.fetch_user(self.user_id)
                notify_embed = discord.Embed(
                    title="Infraction Removed",
                    description=f"An infraction has been removed from your record in **{self.guild.name}**.",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                notify_embed.add_field(name="Infraction ID", value=str(self.inf_id), inline=True)
                notify_embed.add_field(name="Type", value=self.inf_type, inline=True)
                notify_embed.add_field(name="Original Reason", value=self.reason or "None", inline=False)
                notify_embed.add_field(name="Original Date", value=self.timestamp.replace("T", " ")[:19], inline=True)
                notify_embed.add_field(name="Removed By", value=f"{interaction.user.name}#{interaction.user.discriminator}", inline=True)
                notify_embed.set_footer(text=f"Server: {self.guild.name}")
                await user.send(embed=notify_embed)
                result_text = f"Infraction {self.inf_id} deleted and user notified."
            except discord.Forbidden:
                result_text = f"Infraction {self.inf_id} deleted, but couldn't DM the user (DMs disabled or blocked)."
            except Exception as e:
                result_text = f"Infraction {self.inf_id} deleted, but failed to notify user: {e}"
        else:
            result_text = f"Infraction {self.inf_id} deleted silently."

        await interaction.response.edit_message(content=result_text, embed=None, view=None)

        # Log the deletion to the mod log for audit trail
        log_cog = self.cog.bot.get_cog("Logger")
        if log_cog:
            audit_embed = discord.Embed(
                title="Infraction Manually Deleted",
                color=discord.Color.orange(),
                timestamp=datetime.utcnow()
            )
            audit_embed.add_field(name="Infraction ID", value=str(self.inf_id), inline=True)
            audit_embed.add_field(name="Type", value=self.inf_type, inline=True)
            audit_embed.add_field(name="Original Reason", value=self.reason or "None", inline=False)
            audit_embed.add_field(name="Original Date", value=self.timestamp.replace("T", " ")[:19], inline=True)
            audit_embed.add_field(name="Target User ID", value=str(self.user_id), inline=True)
            audit_embed.add_field(name="Deleted By", value=f"{interaction.user.mention} ({interaction.user})", inline=False)
            audit_embed.add_field(name="User Notified", value="Yes" if notify else "No", inline=True)
            audit_embed.set_footer(text=f"Mod ID: {interaction.user.id} | User ID: {self.user_id}")
            await log_cog.send_log(self.guild.id, "infraction_modify", audit_embed)

    @discord.ui.button(label="Delete & Notify", style=discord.ButtonStyle.green)
    async def delete_notify(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Delete the infraction and DM the user."""
        await self._do_delete(interaction, notify=True)

    @discord.ui.button(label="Delete Silently", style=discord.ButtonStyle.grey)
    async def delete_silent(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Delete the infraction without notifying the user."""
        await self._do_delete(interaction, notify=False)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Abort the deletion."""
        await interaction.response.edit_message(content="Deletion cancelled.", embed=None, view=None)


class InfractionRemovalView(discord.ui.View):
    """View for approving or denying infraction auto-removals.

    Uses timeout=None so the view stays active indefinitely after restarts
    (it is manually re-registered via cog_load using the stored message ID).
    """

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
        """Approve the removal — mark infraction as removed and notify the user."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.cog.db_path)
            try:
                conn.execute("""
                    UPDATE infractions
                    SET removed=1, removed_date=?, removed_by=?, pending_approval=0
                    WHERE id=?
                """, (datetime.utcnow().isoformat(), interaction.user.id, self.inf_id))
                conn.commit()
            finally:
                conn.close()

            embed = discord.Embed(
                title="✅ Infraction Removed",
                description="This infraction has been removed from the user's active record.",
                color=discord.Color.green()
            )
            embed.add_field(name="User", value=self.user_tag, inline=True)
            embed.add_field(name="Infraction ID", value=str(self.inf_id), inline=True)
            embed.add_field(name="Type", value=self.inf_type, inline=True)
            embed.add_field(name="Reason", value=self.reason or "None", inline=False)
            embed.add_field(name="Original Date", value=self.timestamp.replace("T", " ")[:19], inline=True)
            embed.add_field(name="Removed By", value=interaction.user.mention, inline=True)
            embed.add_field(name="Removed At", value=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), inline=True)

            await interaction.response.edit_message(embed=embed, view=None)

            # Log to mod audit trail
            log_cog = self.cog.bot.get_cog("Logger")
            if log_cog:
                audit_embed = discord.Embed(
                    title="Infraction Auto-Removal Approved",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                audit_embed.add_field(name="Infraction ID", value=str(self.inf_id), inline=True)
                audit_embed.add_field(name="Type", value=self.inf_type, inline=True)
                audit_embed.add_field(name="Original Reason", value=self.reason or "None", inline=False)
                audit_embed.add_field(name="Original Date", value=self.timestamp.replace("T", " ")[:19], inline=True)
                audit_embed.add_field(name="Target User ID", value=str(self.user_id), inline=True)
                audit_embed.add_field(name="Approved By", value=f"{interaction.user.mention} ({interaction.user})", inline=False)
                audit_embed.set_footer(text=f"Mod ID: {interaction.user.id} | User ID: {self.user_id}")
                await log_cog.send_log(self.guild_id, "infraction_modify", audit_embed)

            # Notify user of the good news
            try:
                user = await self.cog.bot.fetch_user(self.user_id)
                guild = self.cog.bot.get_guild(self.guild_id)
                guild_name = guild.name if guild else "the server"

                notify_embed = discord.Embed(
                    title="✅ Infraction Removed",
                    description=f"Great news! An infraction has been removed from your record in **{guild_name}** for good behavior.",
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
        """Deny the removal — mark to skip future auto-removal checks for this infraction."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.cog.db_path)
            try:
                conn.execute("""
                    UPDATE infractions
                    SET skip_auto_removal=1, pending_approval=0
                    WHERE id=?
                """, (self.inf_id,))
                conn.commit()
            finally:
                conn.close()

            embed = discord.Embed(
                title="❌ Removal Denied",
                description="This infraction will remain active and will not be checked for auto-removal again.",
                color=discord.Color.red()
            )
            embed.add_field(name="User", value=self.user_tag, inline=True)
            embed.add_field(name="Infraction ID", value=str(self.inf_id), inline=True)
            embed.add_field(name="Type", value=self.inf_type, inline=True)
            embed.add_field(name="Reason", value=self.reason or "None", inline=False)
            embed.add_field(name="Original Date", value=self.timestamp.replace("T", " ")[:19], inline=True)
            embed.add_field(name="Decision By", value=interaction.user.mention, inline=True)
            embed.add_field(name="Decision At", value=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), inline=True)

            await interaction.response.edit_message(embed=embed, view=None)

            # Log to mod audit trail
            log_cog = self.cog.bot.get_cog("Logger")
            if log_cog:
                audit_embed = discord.Embed(
                    title="Infraction Auto-Removal Denied",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                audit_embed.add_field(name="Infraction ID", value=str(self.inf_id), inline=True)
                audit_embed.add_field(name="Type", value=self.inf_type, inline=True)
                audit_embed.add_field(name="Original Reason", value=self.reason or "None", inline=False)
                audit_embed.add_field(name="Original Date", value=self.timestamp.replace("T", " ")[:19], inline=True)
                audit_embed.add_field(name="Target User ID", value=str(self.user_id), inline=True)
                audit_embed.add_field(name="Denied By", value=f"{interaction.user.mention} ({interaction.user})", inline=False)
                audit_embed.set_footer(text=f"Mod ID: {interaction.user.id} | User ID: {self.user_id}")
                await log_cog.send_log(self.guild_id, "infraction_modify", audit_embed)

        except Exception as e:
            await interaction.response.send_message(f"Error denying removal: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(InfractionCommand(bot))
