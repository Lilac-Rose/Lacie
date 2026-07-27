import asyncio
import time
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands
from .loader import ModerationBase
from utils.constants import LILAC_ID

SCAN_WORKERS = 5      # Parallel time-window workers per channel
PROGRESS_EVERY = 500  # Call on_progress every N messages scanned


async def safe_delete_user_messages(channel: discord.TextChannel, user_id: int, on_progress=None):
    """Delete all messages from a user in one channel.

    Uses a two-phase approach to handle Discord's 14-day bulk-delete limit:

    Phase 1: bulk-delete recent messages (< 14 days) via channel.purge().
    Phase 2: split the remaining history into parallel time windows so the
             sequential fetch bottleneck is reduced by ~SCAN_WORKERS times.

    Parameters
    ----------
    channel:
        The text channel to scan.
    user_id:
        ID of the user whose messages should be deleted.
    on_progress:
        Optional callback ``on_progress(scanned, deleted)`` called every
        PROGRESS_EVERY messages scanned, so the caller can update a status
        message without spamming Discord's API.

    Returns
    -------
    tuple[int, str | None]
        ``(deleted_count, error_string)`` — error_string is None on success.
    """
    deleted_count = 0
    scanned_count = 0
    count_lock = asyncio.Lock()
    # Cap concurrent individual deletes at 2 to stay under rate limits
    delete_sem = asyncio.Semaphore(2)

    async def scan_and_delete_window(after_dt: datetime, before_dt: datetime):
        nonlocal deleted_count, scanned_count
        async for message in channel.history(
            limit=None, after=after_dt, before=before_dt, oldest_first=True
        ):
            async with count_lock:
                scanned_count += 1
                sc, dc = scanned_count, deleted_count

            if sc % PROGRESS_EVERY == 0 and on_progress:
                on_progress(sc, dc)

            if message.author.id != user_id:
                continue

            async with delete_sem:
                try:
                    await message.delete()
                    async with count_lock:
                        deleted_count += 1
                    await asyncio.sleep(0.5)
                except discord.NotFound:
                    pass
                except discord.HTTPException as e:
                    if e.status == 429:
                        retry_after = float(e.response.headers.get("Retry-After", 1))
                        await asyncio.sleep(retry_after)
                    else:
                        raise

    try:
        # Phase 1: bulk-delete messages newer than 14 days
        deleted = await channel.purge(limit=None, check=lambda m: m.author.id == user_id)
        deleted_count += len(deleted)
        if on_progress:
            on_progress(0, deleted_count)

        # Phase 2: scan older history in parallel time windows
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=14)
        start = channel.created_at.replace(tzinfo=timezone.utc)

        if start < cutoff:
            total_seconds = (cutoff - start).total_seconds()
            chunk = total_seconds / SCAN_WORKERS
            windows = [
                (
                    start + timedelta(seconds=i * chunk),
                    start + timedelta(seconds=(i + 1) * chunk),
                )
                for i in range(SCAN_WORKERS)
            ]
            await asyncio.gather(*(scan_and_delete_window(a, b) for a, b in windows))

        if on_progress:
            on_progress(scanned_count, deleted_count)

        return deleted_count, None
    except discord.Forbidden:
        return deleted_count, "No permissions"
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return deleted_count, str(e)


class Purge(ModerationBase):
    """Commands for purging messages.

    Standard purge commands delete messages in the current channel up to a
    given message ID anchor. The !purgememberall command is destructive — it
    scans every channel in a set of allowed categories and deletes all messages
    from a specific user. It is restricted to the server owner and runs as a
    cancellable background task with a live progress ticker.
    """

    def __init__(self, bot):
        super().__init__(bot)
        # Tracks active purgememberall tasks so duplicates and !cancelpurge can be managed
        self._active_purges: dict[int, asyncio.Task] = {}  # guild_id -> task

    async def fetch_after_message(self, ctx, message_id: int):
        """Fetch a message by ID from the current channel, sending an error on failure.

        Parameters
        ----------
        message_id:
            Discord message ID to anchor the purge range.

        Returns
        -------
        discord.Message | None
            The fetched message, or None if not found.
        """
        try:
            msg = await ctx.channel.fetch_message(message_id)
            return msg
        except discord.NotFound:
            await ctx.send(f"❌ Message ID {message_id} not found in this channel.")
            return None
        except discord.HTTPException as e:
            await ctx.send(f"❌ Error fetching message ID {message_id}: {e}")
            return None

    async def purge_messages(self, ctx, check=None, after_message=None, limit: int = 100):
        """Bulk-delete messages in the current channel up to a limit.

        Sends a status message that is edited in-place with the outcome.
        Logs the operation to the mod log on success.

        Parameters
        ----------
        check:
            Optional filter function passed to channel.purge().
        after_message:
            If provided, only messages after this one are deleted. The anchor
            message itself is also deleted.
        limit:
            Maximum number of messages to delete (capped at 1000).
        """
        if not ctx.guild:
            return
        if not ctx.channel.permissions_for(ctx.guild.me).manage_messages:
            await ctx.send("❌ I don't have permission to manage messages in this channel!")
            return

        limit = min(limit, 1000)
        status_msg = await ctx.send(f"🗑️ Starting purge... (limit={limit})")

        try:
            if after_message:
                try:
                    await after_message.delete()
                except Exception as e:
                    await status_msg.edit(content=f"⚠️ Could not delete target message: {e}")

            if check:
                deleted = await ctx.channel.purge(
                    limit=limit, check=check, after=after_message, before=ctx.message
                )
            else:
                deleted = await ctx.channel.purge(
                    limit=limit, after=after_message, before=ctx.message
                )

            try:
                await ctx.message.delete()
            except Exception as e:
                await status_msg.edit(content=f"⚠️ Could not delete command message: {e}")

            total_deleted = len(deleted) + (1 if after_message else 0)
            await status_msg.edit(content=f"✅ Purge complete! Deleted **{total_deleted}** message(s).")

            # Log the purge operation to the mod log
            logger = self.bot.get_cog("Logger")
            if logger and ctx.guild:
                embed = discord.Embed(
                    title="Purge Executed",
                    color=discord.Color.orange(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(name="Moderator", value=f"{ctx.author.mention} ({ctx.author})", inline=False)
                embed.add_field(name="Channel", value=ctx.channel.mention, inline=True)
                embed.add_field(name="Messages Deleted", value=str(total_deleted), inline=True)
                if after_message:
                    embed.add_field(name="After Message ID", value=str(after_message.id), inline=True)
                embed.set_footer(text=f"Mod ID: {ctx.author.id}")
                await logger.send_log(ctx.guild.id, "message_bulk_delete", embed, ctx.channel.id)

        except discord.Forbidden:
            await status_msg.edit(content="❌ Forbidden: I don't have permission to delete messages!")
        except discord.HTTPException as e:
            await status_msg.edit(content=f"❌ HTTPException during purge: {e}")
        except Exception as e:
            await status_msg.edit(content=f"❌ Unexpected error during purge: {e}")

    @commands.command(name="purge")
    @ModerationBase.is_senior_admin()
    async def purge(self, ctx, message_id: int):
        """Delete all messages in this channel from the given message ID to now.

        Parameters
        ----------
        message_id:
            ID of the oldest message to include in the purge range.
        """
        status_msg = await ctx.send(f"🗑️ Purge command received for message ID {message_id}...")
        after_message = await self.fetch_after_message(ctx, message_id)
        if not after_message:
            await status_msg.edit(content="❌ Could not find the target message. Purge aborted.")
            return
        await self.purge_messages(ctx, after_message=after_message)

    @commands.command(name="purgemember", aliases=["purgeuser", "purgeu", "purgem"])
    @ModerationBase.is_senior_admin()
    async def purge_member(self, ctx, member: discord.Member, message_id: int):
        """Delete messages from a specific member from the given message ID to now.

        Parameters
        ----------
        member:
            The member whose messages to delete.
        message_id:
            ID of the oldest message to include in the purge range.
        """
        status_msg = await ctx.send(f"🗑️ Purge command received for member {member} up to message ID {message_id}...")
        after_message = await self.fetch_after_message(ctx, message_id)
        if not after_message:
            await status_msg.edit(content="❌ Could not find the target message. Purge aborted.")
            return
        await self.purge_messages(ctx, check=lambda m: m.author.id == member.id, after_message=after_message)

    @commands.command(name="purgebot", aliases=["purgebots", "purgeb"])
    @ModerationBase.is_senior_admin()
    async def purge_bots(self, ctx, message_id: int):
        """Delete bot messages from the given message ID to now.

        Parameters
        ----------
        message_id:
            ID of the oldest message to include in the purge range.
        """
        status_msg = await ctx.send(f"🗑️ Purge command received for bots up to message ID {message_id}...")
        after_message = await self.fetch_after_message(ctx, message_id)
        if not after_message:
            await status_msg.edit(content="❌ Could not find the target message. Purge aborted.")
            return
        await self.purge_messages(ctx, check=lambda m: m.author.bot, after_message=after_message)

    @commands.command(name="purgecontains", aliases=["purgec", "purgetext"])
    @ModerationBase.is_senior_admin()
    async def purge_contains(self, ctx, message_id: int, *, text: str):
        """Delete messages containing specific text from the given message ID to now.

        Parameters
        ----------
        message_id:
            ID of the oldest message to include in the purge range.
        text:
            Case-insensitive substring to match against message content.
        """
        status_msg = await ctx.send(f"🗑️ Purge command received for messages containing '{text}' up to message ID {message_id}...")
        after_message = await self.fetch_after_message(ctx, message_id)
        if not after_message:
            await status_msg.edit(content="❌ Could not find the target message. Purge aborted.")
            return
        await self.purge_messages(ctx, check=lambda m: text.lower() in m.content.lower(), after_message=after_message)

    @commands.command(name="purgeembeds", aliases=["purgee", "purgeembed"])
    @ModerationBase.is_senior_admin()
    async def purge_embeds(self, ctx, message_id: int):
        """Delete messages that contain embeds from the given message ID to now.

        Parameters
        ----------
        message_id:
            ID of the oldest message to include in the purge range.
        """
        status_msg = await ctx.send(f"🗑️ Purge command received for messages with embeds up to message ID {message_id}...")
        after_message = await self.fetch_after_message(ctx, message_id)
        if not after_message:
            await status_msg.edit(content="❌ Could not find the target message. Purge aborted.")
            return
        await self.purge_messages(ctx, check=lambda m: len(m.embeds) > 0, after_message=after_message)

    @commands.command(name="purgememberall", aliases=["purgeuserall", "purgeua", "purgeallm"])
    @ModerationBase.is_admin()
    async def purge_member_all(self, ctx, user_id: int):
        """Delete all messages from a user across all text channels in the server (owner only, requires confirmation).

        Only the server owner (LILAC_ID) may run this command — it is too
        destructive for general staff use. Runs as a cancellable background task
        with a live progress embed that updates every 3 seconds to avoid hitting
        Discord's edit rate limit.

        Parameters
        ----------
        user_id:
            Discord user ID of the target whose messages will be wiped.
        """
        if not ctx.guild:
            return

        if ctx.author.id != LILAC_ID:
            await ctx.send("❌ This command can only be used by the server owner — it's too destructive for general staff use.")
            return

        member = ctx.guild.get_member(user_id)
        user_display = str(member) if member else f"User ID {user_id}"

        class ConfirmView(discord.ui.View):
            def __init__(self, author: discord.User):
                super().__init__(timeout=30)
                self.author = author
                self.value = None

            async def interaction_check(self, interaction: discord.Interaction):
                if interaction.user.id != self.author.id:
                    await interaction.response.send_message("❌ You can't confirm someone else's purge command.", ephemeral=True)
                    return False
                return True

            @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
            async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.value = True
                await interaction.response.edit_message(content="🧹 Purge confirmed. Starting...", view=None)
                self.stop()

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.value = False
                await interaction.response.edit_message(content="❌ Purge cancelled.", view=None)
                self.stop()

        view = ConfirmView(ctx.author)
        msg = await ctx.send(
            f"⚠️ **Confirm Purge** ⚠️\n"
            f"You're about to delete **all messages** from **{user_display}** across **every channel**.\n\n"
            f"Are you sure you want to continue?",
            view=view
        )

        await view.wait()

        if view.value is None:
            await msg.edit(content="⏰ Confirmation timed out. Purge cancelled.", view=None)
            return
        if view.value is False:
            return

        if ctx.guild.id in self._active_purges and not self._active_purges[ctx.guild.id].done():
            await msg.edit(content="❌ A purge is already running. Use `cancelpurge` to stop it first.")
            return

        task = asyncio.create_task(self._purge_user_messages(ctx, user_id, user_display, msg))
        self._active_purges[ctx.guild.id] = task
        # Auto-clean the registry when the task completes
        task.add_done_callback(lambda _: self._active_purges.pop(ctx.guild.id, None))

    @commands.command(name="cancelpurge", aliases=["stoppurge"])
    @ModerationBase.is_admin()
    async def cancel_purge(self, ctx):
        """Cancel an in-progress purgememberall."""
        task = self._active_purges.get(ctx.guild.id)
        if not task or task.done():
            await ctx.send("❌ No purge is currently running.")
            return
        task.cancel()
        await ctx.send("🛑 Purge cancellation requested.")

    async def _purge_user_messages(self, ctx, user_id: int, user_display: str, msg: discord.Message):
        """Background purge task — processes channels concurrently with per-channel progress.

        Restricts scanning to a hardcoded set of category IDs to avoid touching
        bot-internal or announcement channels. Uses a semaphore to cap concurrency
        at 5 channels at once. A ticker coroutine edits the status message every 3
        seconds so staff can watch progress without hammering the API.

        Parameters
        ----------
        user_id:
            ID of the user whose messages are being deleted.
        user_display:
            Human-readable display name used in status messages.
        msg:
            The Discord message to edit in-place with live progress.
        """
        CATEGORY_IDS = {
            962737280735408218,
            1229700264848789594,
            876772600704020531,
            1087353136198451241,
            876772600704020532,
        }

        channels = [
            ch for ch in ctx.guild.text_channels
            if ch.category_id in CATEGORY_IDS
        ]

        total_channels = len(channels)
        lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(5)

        # Per-channel stats: scanned, deleted, done, error
        stats: dict[str, dict] = {
            ch.name: {"scanned": 0, "deleted": 0, "done": False, "error": None}
            for ch in channels
        }
        failed_channels: list[str] = []

        def build_status() -> str:
            done_channels = [n for n, s in stats.items() if s["done"]]
            active = [n for n, s in stats.items() if not s["done"] and s["scanned"] > 0]
            total_deleted = sum(s["deleted"] for s in stats.values())
            completed = len(done_channels)

            lines = [
                f"🧹 **Purging {user_display}** — {completed}/{total_channels} channels done · {total_deleted:,} deleted",
                "",
            ]

            if active:
                lines.append("**Scanning:**")
                for name in active:
                    s = stats[name]
                    lines.append(f"› **#{name}** — {s['scanned']:,} scanned · {s['deleted']:,} deleted")
                lines.append("")

            if done_channels:
                # Show last 5 completed to keep message short
                shown = done_channels[-5:]
                summary_parts = [f"#{n} ({stats[n]['deleted']:,})" for n in shown]
                prefix = f"**Done ({completed}):** " + " · ".join(summary_parts)
                if completed > 5:
                    prefix += f" · *(+{completed - 5} more)*"
                lines.append(prefix)

            return "\n".join(lines)

        # Ticker: edit the Discord message every 3s so we don't get rate limited
        stop_ticker = asyncio.Event()
        last_edit_time = [0.0]

        async def ticker():
            while not stop_ticker.is_set():
                await asyncio.sleep(3)
                if stop_ticker.is_set():
                    break
                try:
                    await msg.edit(content=build_status())
                    last_edit_time[0] = time.monotonic()
                except Exception:
                    pass

        ticker_task = asyncio.create_task(ticker())

        async def purge_channel(channel: discord.TextChannel):
            if not channel.permissions_for(ctx.guild.me).manage_messages:
                async with lock:
                    stats[channel.name]["done"] = True
                    stats[channel.name]["error"] = "No perms"
                    failed_channels.append(f"#{channel.name}: No perms")
                return

            def on_progress(scanned: int, deleted: int):
                stats[channel.name]["scanned"] = scanned
                stats[channel.name]["deleted"] = deleted

            async with semaphore:
                deleted_count, error = await safe_delete_user_messages(channel, user_id, on_progress)

            async with lock:
                stats[channel.name]["scanned"] = max(stats[channel.name]["scanned"], deleted_count)
                stats[channel.name]["deleted"] = deleted_count
                stats[channel.name]["done"] = True
                if error:
                    stats[channel.name]["error"] = error
                    failed_channels.append(f"#{channel.name}: {error}")

        try:
            await asyncio.gather(*(purge_channel(ch) for ch in channels))
        except asyncio.CancelledError:
            stop_ticker.set()
            ticker_task.cancel()
            total_deleted = sum(s["deleted"] for s in stats.values())
            await msg.edit(content=(
                f"🛑 **Purge cancelled.**\n"
                f"🗑️ Deleted **{total_deleted:,}** message(s) before stopping."
            ))
            return

        stop_ticker.set()
        ticker_task.cancel()

        total_deleted = sum(s["deleted"] for s in stats.values())
        summary = (
            f"✅ **Finished purging {user_display}.**\n"
            f"🗑️ Deleted **{total_deleted:,}** message(s) across {total_channels} channels."
        )
        if failed_channels:
            summary += f"\n⚠️ Skipped/Errored: {', '.join(failed_channels[:10])}"
            if len(failed_channels) > 10:
                summary += f" (and {len(failed_channels) - 10} more...)"

        await msg.edit(content=summary)

        # Log the purgememberall operation to the mod log
        logger = self.bot.get_cog("Logger")
        if logger and ctx.guild:
            embed = discord.Embed(
                title="Purge All — User Messages Wiped",
                color=discord.Color.dark_red(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Executed By", value=f"{ctx.author.mention} ({ctx.author})", inline=False)
            embed.add_field(name="Target", value=user_display, inline=True)
            embed.add_field(name="Target ID", value=str(user_id), inline=True)
            embed.add_field(name="Messages Deleted", value=f"{total_deleted:,}", inline=True)
            embed.add_field(name="Channels Scanned", value=str(total_channels), inline=True)
            if failed_channels:
                embed.add_field(name="Skipped Channels", value=", ".join(failed_channels[:10]), inline=False)
            embed.set_footer(text=f"Mod ID: {ctx.author.id}")
            await logger.send_log(ctx.guild.id, "message_bulk_delete", embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Purge(bot))
