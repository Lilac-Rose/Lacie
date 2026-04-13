import asyncio
import discord
from discord.ext import commands
from .loader import ModerationBase


async def safe_delete_user_messages(channel: discord.TextChannel, user_id: int, timeout: int = 20):
    """Safely delete all messages from a user in one channel with a timeout."""
    deleted_count = 0

    async def do_purge():
        nonlocal deleted_count
        async for message in channel.history(limit=None, oldest_first=False):
            if message.author.id == user_id:
                try:
                    await message.delete()
                    deleted_count += 1
                    await asyncio.sleep(0.2)
                except discord.Forbidden:
                    raise PermissionError("Missing permissions")
                except discord.HTTPException as e:
                    if "rate limit" in str(e).lower():
                        await asyncio.sleep(1)
                    else:
                        raise e

    try:
        await asyncio.wait_for(do_purge(), timeout=timeout)
        return deleted_count, None
    except asyncio.TimeoutError:
        return deleted_count, f"Timeout after {timeout}s"
    except PermissionError:
        return deleted_count, "No permissions"
    except Exception as e:
        return deleted_count, str(e)


class Purge(ModerationBase):
    """Commands for purging messages"""

    async def fetch_after_message(self, ctx, message_id: int):
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

        except discord.Forbidden:
            await status_msg.edit(content="❌ Forbidden: I don't have permission to delete messages!")
        except discord.HTTPException as e:
            await status_msg.edit(content=f"❌ HTTPException during purge: {e}")
        except Exception as e:
            await status_msg.edit(content=f"❌ Unexpected error during purge: {e}")

    @commands.command(name="purge")
    @ModerationBase.is_admin()
    async def purge(self, ctx, message_id: int):
        status_msg = await ctx.send(f"🗑️ Purge command received for message ID {message_id}...")
        after_message = await self.fetch_after_message(ctx, message_id)
        if not after_message:
            await status_msg.edit(content="❌ Could not find the target message. Purge aborted.")
            return
        await self.purge_messages(ctx, after_message=after_message)

    @commands.command(name="purgemember", aliases=["purgeuser", "purgeu", "purgem"])
    @ModerationBase.is_admin()
    async def purge_member(self, ctx, member: discord.Member, message_id: int):
        status_msg = await ctx.send(f"🗑️ Purge command received for member {member} up to message ID {message_id}...")
        after_message = await self.fetch_after_message(ctx, message_id)
        if not after_message:
            await status_msg.edit(content="❌ Could not find the target message. Purge aborted.")
            return
        await self.purge_messages(ctx, check=lambda m: m.author.id == member.id, after_message=after_message)

    @commands.command(name="purgebot", aliases=["purgebots", "purgeb"])
    @ModerationBase.is_admin()
    async def purge_bots(self, ctx, message_id: int):
        status_msg = await ctx.send(f"🗑️ Purge command received for bots up to message ID {message_id}...")
        after_message = await self.fetch_after_message(ctx, message_id)
        if not after_message:
            await status_msg.edit(content="❌ Could not find the target message. Purge aborted.")
            return
        await self.purge_messages(ctx, check=lambda m: m.author.bot, after_message=after_message)

    @commands.command(name="purgecontains", aliases=["purgec", "purgetext"])
    @ModerationBase.is_admin()
    async def purge_contains(self, ctx, message_id: int, *, text: str):
        status_msg = await ctx.send(f"🗑️ Purge command received for messages containing '{text}' up to message ID {message_id}...")
        after_message = await self.fetch_after_message(ctx, message_id)
        if not after_message:
            await status_msg.edit(content="❌ Could not find the target message. Purge aborted.")
            return
        await self.purge_messages(ctx, check=lambda m: text.lower() in m.content.lower(), after_message=after_message)

    @commands.command(name="purgeembeds", aliases=["purgee", "purgeembed"])
    @ModerationBase.is_admin()
    async def purge_embeds(self, ctx, message_id: int):
        status_msg = await ctx.send(f"🗑️ Purge command received for messages with embeds up to message ID {message_id}...")
        after_message = await self.fetch_after_message(ctx, message_id)
        if not after_message:
            await status_msg.edit(content="❌ Could not find the target message. Purge aborted.")
            return
        await self.purge_messages(ctx, check=lambda m: len(m.embeds) > 0, after_message=after_message)

    @commands.command(name="purgememberall", aliases=["purgeuserall", "purgeua", "purgeallm"])
    @ModerationBase.is_admin()
    async def purge_member_all(self, ctx, user_id: int):
        """Delete all messages from a user across all text channels in the server (requires confirmation)."""
        if not ctx.guild:
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
                    await interaction.response.send_message("❌ You can’t confirm someone else’s purge command.", ephemeral=True)
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

        # Run purge in background task so it doesn’t block bot
        asyncio.create_task(self._purge_user_messages(ctx, user_id, user_display, msg))

    async def _purge_user_messages(self, ctx, user_id: int, user_display: str, msg: discord.Message):
        """Background purge task with timeout, per-channel progress, and async safety."""
        total_deleted = 0
        failed_channels = []
        processed = 0
        total_channels = len(ctx.guild.text_channels)

        await msg.edit(content=f"🧹 Starting purge for **{user_display}**...\nTotal channels: {total_channels}")

        for channel in ctx.guild.text_channels:
            processed += 1
            channel_name = channel.name

            try:
                await msg.edit(content=(
                    f"🧹 Working on **#{channel_name}** ({processed}/{total_channels})...\n"
                    f"Deleted so far: **{total_deleted}**"
                ))
            except Exception:
                pass

            if not channel.permissions_for(ctx.guild.me).manage_messages:
                failed_channels.append(f"#{channel_name}: No perms")
                continue

            deleted_count, error = await safe_delete_user_messages(channel, user_id)
            total_deleted += deleted_count

            if error:
                failed_channels.append(f"#{channel_name}: {error}")

        summary = (
            f"✅ Finished purging **{user_display}**.\n"
            f"🗑️ Deleted **{total_deleted}** message(s)."
        )
        if failed_channels:
            summary += f"\n⚠️ Skipped/Errored: {', '.join(failed_channels[:10])}"
            if len(failed_channels) > 10:
                summary += f" (and {len(failed_channels) - 10} more...)"

        await msg.edit(content=summary)


async def setup(bot: commands.Bot):
    await bot.add_cog(Purge(bot))
