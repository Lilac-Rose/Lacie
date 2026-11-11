import random

import discord
from discord.ext import commands

from .loader import ModerationBase

DEFAULT_COUNT = 10
MAX_COUNT = 50
# Upper bound on how far back we scan, so a quiet channel can't make us page
# through its entire history looking for enough unique posters.
HISTORY_SCAN_LIMIT = 1000


class RandomMemberCog(commands.Cog):
    """Cog providing the !random_member prefix command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="random_member", aliases=["randommember"])
    @ModerationBase.is_admin()
    async def random_member(self, ctx, count: int = DEFAULT_COUNT):
        """Pick a random member from the last `count` unique people who chatted here.

        Walks back through the channel's history (skipping the command message
        itself and bots) collecting distinct authors until `count` are found or
        HISTORY_SCAN_LIMIT messages have been checked, then picks one at random.
        Authors who have since left the server are skipped.

        Parameters
        ----------
        count:
            How many recent unique members to pick from. Defaults to 10, max 50.
        """
        if not ctx.guild:
            return

        if count < 1 or count > MAX_COUNT:
            await ctx.send(f"Count must be between 1 and {MAX_COUNT}.")
            return

        candidates: dict[int, discord.Member] = {}
        async for message in ctx.channel.history(limit=HISTORY_SCAN_LIMIT, before=ctx.message):
            author = message.author
            if author.bot or not isinstance(author, discord.Member):
                continue
            if author.id not in candidates:
                candidates[author.id] = author
                if len(candidates) >= count:
                    break

        if not candidates:
            await ctx.send("I couldn't find any recent members in this channel.")
            return

        winner = random.choice(list(candidates.values()))
        pool_note = (
            f"the last {len(candidates)} unique members"
            if len(candidates) >= count
            else f"only {len(candidates)} unique member(s) found (asked for {count})"
        )
        await ctx.send(
            f"🎲 Picked {winner.mention} from {pool_note}.",
            allowed_mentions=discord.AllowedMentions(users=[winner]),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RandomMemberCog(bot))
