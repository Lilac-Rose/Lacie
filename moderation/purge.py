import discord
from discord.ext import commands
from .loader import ModerationBase
from typing import Optional

class Purge(ModerationBase):
    """Commands for purging messages"""

    async def fetch_after_message(self, ctx, message_id: int):
        """Helper to fetch a message and handle errors"""
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
        """Generic purge helper with verbose debug info, includes the target message itself"""
        if not ctx.channel.permissions_for(ctx.guild.me).manage_messages:
            await ctx.send("❌ I don't have permission to manage messages in this channel!")
            return

        limit = min(limit, 1000)
        status_msg = await ctx.send(f"🗑️ Starting purge... (limit={limit})")

        try:
            # Delete the target message first if provided
            if after_message:
                try:
                    await after_message.delete()
                except Exception as e:
                    await status_msg.edit(content=f"⚠️ Could not delete target message: {e}")

            # Purge messages after the target
            if check:
                deleted = await ctx.channel.purge(
                    limit=limit,
                    check=check,
                    after=after_message,
                    before=ctx.message
                )
            else:
                deleted = await ctx.channel.purge(
                    limit=limit,
                    after=after_message,
                    before=ctx.message
                )

            # Delete the command message
            try: 
                await ctx.message.delete()
            except Exception as e:
                await status_msg.edit(content=f"⚠️ Could not delete command message: {e}")

            # Update status message
            try:
                total_deleted = len(deleted) + (1 if after_message else 0)
                await status_msg.edit(content=f"✅ Purge complete! Deleted **{total_deleted}** message(s).")
            except Exception as e:
                await ctx.send(f"⚠️ Could not update status message: {e}")

        except discord.Forbidden:
            await status_msg.edit(content="❌ Forbidden: I don't have permission to delete messages!")
        except discord.HTTPException as e:
            await status_msg.edit(content=f"❌ HTTPException during purge: {e}")
        except Exception as e:
            await status_msg.edit(content=f"❌ Unexpected error during purge: {e}")

    @commands.command(name="purge")
    @ModerationBase.is_admin()
    async def purge(self, ctx, message_id: int):
        """Delete messages up to and including a specific message ID."""
        status_msg = await ctx.send(f"🗑️ Purge command received for message ID {message_id}...")
        after_message = await self.fetch_after_message(ctx, message_id)
        if not after_message:
            await status_msg.edit(content="❌ Could not find the target message. Purge aborted.")
            return
        await self.purge_messages(ctx, after_message=after_message)

    @commands.command(name="purgemember", aliases=["purgeuser", "purgeu", "purgem"])
    @ModerationBase.is_admin()
    async def purge_member(self, ctx, member: discord.Member, message_id: int):
        """Delete messages from a member up to and including a specific message ID."""
        status_msg = await ctx.send(f"🗑️ Purge command received for member {member} up to message ID {message_id}...")
        after_message = await self.fetch_after_message(ctx, message_id)
        if not after_message:
            await status_msg.edit(content="❌ Could not find the target message. Purge aborted.")
            return
        await self.purge_messages(ctx, check=lambda m: m.author.id == member.id, after_message=after_message)

    @commands.command(name="purgebot", aliases=["purgebots", "purgeb"])
    @ModerationBase.is_admin()
    async def purge_bots(self, ctx, message_id: int):
        """Delete messages from bots up to and including a specific message ID."""
        status_msg = await ctx.send(f"🗑️ Purge command received for bots up to message ID {message_id}...")
        after_message = await self.fetch_after_message(ctx, message_id)
        if not after_message:
            await status_msg.edit(content="❌ Could not find the target message. Purge aborted.")
            return
        await self.purge_messages(ctx, check=lambda m: m.author.bot, after_message=after_message)

    @commands.command(name="purgecontains", aliases=["purgec", "purgetext"])
    @ModerationBase.is_admin()
    async def purge_contains(self, ctx, message_id: int, *, text: str):
        """Delete messages containing text up to and including a specific message ID."""
        status_msg = await ctx.send(f"🗑️ Purge command received for messages containing '{text}' up to message ID {message_id}...")
        after_message = await self.fetch_after_message(ctx, message_id)
        if not after_message:
            await status_msg.edit(content="❌ Could not find the target message. Purge aborted.")
            return
        await self.purge_messages(ctx, check=lambda m: text.lower() in m.content.lower(), after_message=after_message)

    @commands.command(name="purgeembeds", aliases=["purgee", "purgeembed"])
    @ModerationBase.is_admin()
    async def purge_embeds(self, ctx, message_id: int):
        """Delete messages with embeds up to and including a specific message ID."""
        status_msg = await ctx.send(f"🗑️ Purge command received for messages with embeds up to message ID {message_id}...")
        after_message = await self.fetch_after_message(ctx, message_id)
        if not after_message:
            await status_msg.edit(content="❌ Could not find the target message. Purge aborted.")
            return
        await self.purge_messages(ctx, check=lambda m: len(m.embeds) > 0, after_message=after_message)

async def setup(bot: commands.Bot):
    await bot.add_cog(Purge(bot))
