import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiosqlite
import random
import os
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Optional

from reminders.reminder import parse_timeframe, parse_datetime
from moderation.loader import ModerationBase
from utils.logger import get_logger

logger = get_logger(__name__)

ADMIN_ROLE_IDS = {
    int(role_id.strip())
    for role_id in os.getenv("ADMIN_ROLE_IDS", "").split(",")
    if role_id.strip().isdigit()
}

GIVEAWAY_EMOJI = "🎉"


def _is_admin(user: discord.Member) -> bool:
    from utils.constants import LILAC_ID
    return user.id == LILAC_ID or any(r.id in ADMIN_ROLE_IDS for r in user.roles)


class GiveawayRollAgainView(discord.ui.View):
    def __init__(self, bot: commands.Bot, giveaway_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.giveaway_id = giveaway_id
        btn = discord.ui.Button(
            label="🔄 Roll Again",
            style=discord.ButtonStyle.primary,
            custom_id=f"giveaway_roll_{giveaway_id}",
        )
        btn.callback = self._roll_callback
        self.add_item(btn)

    async def _roll_callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not _is_admin(interaction.user):
            return await interaction.response.send_message(
                "Only admins can re-roll a giveaway.", ephemeral=True
            )

        await interaction.response.defer()

        db_path = Path(__file__).parent.parent / "data" / "giveaways.db"
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT channel_id, message_id, prize FROM giveaways WHERE id = ?",
                (self.giveaway_id,),
            ) as cur:
                row = await cur.fetchone()

        if not row:
            return await interaction.followup.send("Giveaway not found.", ephemeral=True)

        channel_id, message_id, prize = row
        channel = self.bot.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.abc.Messageable):
            return await interaction.followup.send("Giveaway channel not found.", ephemeral=True)

        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            return await interaction.followup.send(
                "Giveaway message was deleted.", ephemeral=True
            )

        reaction = discord.utils.get(message.reactions, emoji=GIVEAWAY_EMOJI)
        users = [u async for u in reaction.users() if not u.bot] if reaction else []
        if not users:
            return await interaction.followup.send(
                "No eligible participants to re-roll.", ephemeral=True
            )

        winner = random.choice(users)

        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "UPDATE giveaways SET winner_id = ? WHERE id = ?",
                (winner.id, self.giveaway_id),
            )
            await db.commit()

        embed = discord.Embed(
            title="🔄 Re-rolled!",
            description=f"The new winner of **{prize}** is {winner.mention}!\nCongratulations!",
            color=discord.Color.gold(),
            timestamp=datetime.now(dt_timezone.utc),
        )
        await interaction.followup.send(
            embed=embed,
            view=GiveawayRollAgainView(self.bot, self.giveaway_id),
        )


class GiveawayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "data" / "giveaways.db"

    async def cog_load(self):
        await self._setup_db()
        # Re-register persistent roll-again views for already-ended giveaways so
        # buttons continue to work after a restart.
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT id FROM giveaways WHERE ended = 1") as cur:
                rows = await cur.fetchall()
        for (giveaway_id,) in rows:
            self.bot.add_view(GiveawayRollAgainView(self.bot, giveaway_id))

        if not self.check_giveaways.is_running():
            self.check_giveaways.start()

    async def cog_unload(self):
        self.check_giveaways.cancel()

    async def _setup_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS giveaways (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    INTEGER NOT NULL,
                    channel_id  INTEGER NOT NULL,
                    message_id  INTEGER,
                    prize       TEXT    NOT NULL,
                    deadline    TEXT    NOT NULL,
                    ended       INTEGER NOT NULL DEFAULT 0,
                    winner_id   INTEGER
                )
                """
            )
            await db.commit()

    # ── Slash commands ────────────────────────────────────────────────────────

    giveaway_group = app_commands.Group(name="giveaway", description="Giveaway commands")

    @giveaway_group.command(
        name="start",
        description="Start a giveaway (admin only)",
    )
    @app_commands.describe(
        prize="What is being given away",
        deadline="Duration ('2h', '3d') or date/time ('April 5 3pm')",
        timezone="Timezone for date/time deadlines, e.g. 'US/Eastern' (default: UTC)",
    )
    @ModerationBase.is_admin()
    async def giveaway_start(
        self,
        interaction: discord.Interaction,
        prize: str,
        deadline: str,
        timezone: Optional[str] = None,
    ):
        # Parse deadline — try duration first, then datetime string
        try:
            delta = parse_timeframe(deadline)
            ends_at = datetime.now(dt_timezone.utc) + delta
        except ValueError:
            try:
                ends_at = parse_datetime(deadline, timezone)
            except ValueError as e:
                return await interaction.response.send_message(str(e), ephemeral=True)

        unix_ts = int(ends_at.timestamp())

        # Persist before posting so we have an ID
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                INSERT INTO giveaways (guild_id, channel_id, prize, deadline)
                VALUES (?, ?, ?, ?)
                """,
                (interaction.guild_id, interaction.channel_id, prize, ends_at.isoformat()),
            )
            giveaway_id = cur.lastrowid
            await db.commit()

        embed = discord.Embed(
            title=f"{GIVEAWAY_EMOJI} Giveaway!",
            description=(
                f"React with {GIVEAWAY_EMOJI} to enter!\n\n"
                f"**Prize:** {prize}\n"
                f"**Ends:** <t:{unix_ts}:F> (<t:{unix_ts}:R>)"
            ),
            color=discord.Color.purple(),
            timestamp=ends_at,
        )
        embed.set_footer(text=f"Giveaway #{giveaway_id} • Ends at")

        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()

        # Add the entry reaction
        await msg.add_reaction(GIVEAWAY_EMOJI)

        # Store the message ID so the task can fetch reactions later
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE giveaways SET message_id = ? WHERE id = ?",
                (msg.id, giveaway_id),
            )
            await db.commit()

    # ── Background task ───────────────────────────────────────────────────────

    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        now = datetime.now(dt_timezone.utc)
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, channel_id, message_id, prize FROM giveaways "
                "WHERE ended = 0 AND deadline <= ?",
                (now.isoformat(),),
            ) as cur:
                due = await cur.fetchall()

        for giveaway_id, channel_id, message_id, prize in due:
            await self._end_giveaway(giveaway_id, channel_id, message_id, prize)

    async def _end_giveaway(
        self,
        giveaway_id: int,
        channel_id: int,
        message_id: int | None,
        prize: str,
    ):
        # Mark ended immediately to prevent double-firing
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE giveaways SET ended = 1 WHERE id = ?",
                (giveaway_id,),
            )
            await db.commit()

        channel = self.bot.get_channel(channel_id)
        if channel is None or not isinstance(channel, discord.abc.Messageable):
            logger.warning(f"Giveaway #{giveaway_id}: channel {channel_id} not found")
            return

        # Try to fetch reactions from the original message
        users: list[discord.User] = []
        if message_id:
            try:
                msg = await channel.fetch_message(message_id)
                reaction = discord.utils.get(msg.reactions, emoji=GIVEAWAY_EMOJI)
                if reaction:
                    users = [u async for u in reaction.users() if not u.bot]
            except discord.NotFound:
                logger.warning(f"Giveaway #{giveaway_id}: message {message_id} not found")

        view = GiveawayRollAgainView(self.bot, giveaway_id)
        self.bot.add_view(view)

        if not users:
            embed = discord.Embed(
                title=f"{GIVEAWAY_EMOJI} Giveaway Ended",
                description=f"**Prize:** {prize}\n\nNo one entered — no winner this time.",
                color=discord.Color.greyple(),
                timestamp=datetime.now(dt_timezone.utc),
            )
            await channel.send(embed=embed, view=view)
            return

        winner = random.choice(users)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE giveaways SET winner_id = ? WHERE id = ?",
                (winner.id, giveaway_id),
            )
            await db.commit()

        embed = discord.Embed(
            title=f"{GIVEAWAY_EMOJI} Giveaway Ended!",
            description=(
                f"**Prize:** {prize}\n\n"
                f"The winner is {winner.mention}!\nCongratulations! 🎊"
            ),
            color=discord.Color.gold(),
            timestamp=datetime.now(dt_timezone.utc),
        )
        embed.set_footer(text=f"Giveaway #{giveaway_id}")
        await channel.send(embed=embed, view=view)

    @check_giveaways.before_loop
    async def before_check_giveaways(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(GiveawayCog(bot))
