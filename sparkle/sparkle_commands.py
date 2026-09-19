import discord
from discord.ext import commands
from discord import app_commands
from discord.utils import escape_markdown
from typing import Optional
from .database import get_db
import asyncio
import datetime
import sqlite3
from pathlib import Path
from embed.embed_color import get_embed_color


class SparkleCommands(commands.Cog):
    """Cog providing the /sparkle slash-command group for viewing sparkle counts and stats.

    Subcommands:
    - check       — per-user sparkle counts by type.
    - info        — explanation of sparkle probabilities.
    - leaderboard — randomly ordered server leaderboard (up to 20 entries).
    - stats       — server-wide totals, message-per-sparkle ratios, and timing data.

    All database reads are offloaded to a thread executor because sparkle.db
    uses the synchronous sqlite3 driver.
    """

    def __init__(self, bot):
        self.bot = bot
        self.sparkle_emojis = {
            "epic": "💫",
            "rare": "🌟",
            "regular": "✨"
        }

    sparkle_group = app_commands.Group(
        name="sparkle",
        description="Sparkle tracking and information"
    )

    # ========== /sparkle check ==========
    @sparkle_group.command(name="check", description="Check your sparkle count or another user's")
    @app_commands.describe(user="The user to check sparkle count for (leave empty for yourself)")
    async def sparkle_check(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        """Show epic, rare, regular, and total sparkle counts for the target member."""
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        user = user or interaction.user

        def db_task():
            conn = get_db()
            cursor = conn.execute(
                """
                SELECT epic, rare, regular,
                       (epic + rare + regular) as total
                FROM sparkles
                WHERE server_id = ? AND user_id = ?
                """,
                (str(interaction.guild.id), str(user.id))
            )
            result = cursor.fetchone()
            conn.close()
            return result

        result = await asyncio.to_thread(db_task)

        if not result:
            await interaction.response.send_message(
                f"{user.display_name} has no sparkles yet!",
                ephemeral=True
            )
            return

        epic, rare, regular, total = result
        embed = discord.Embed(
            title=f"{user.display_name}'s Sparkles",
            color=get_embed_color(interaction.user.id)
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(
            name="Totals",
            value=(
                f"{self.sparkle_emojis['epic']} **Epic:** {epic}\n"
                f"{self.sparkle_emojis['rare']} **Rare:** {rare}\n"
                f"{self.sparkle_emojis['regular']} **Regular:** {regular}\n"
                f"**Total:** {total}"
            ),
            inline=False
        )

        await interaction.response.send_message(embed=embed)

    # ========== /sparkle info ==========
    @sparkle_group.command(name="info", description="Learn about sparkles and how they work")
    async def sparkle_info(self, interaction: discord.Interaction):
        """Send an embed explaining each sparkle type and its probability."""
        embed = discord.Embed(
            title="✨ Sparkles ✨",
            description=(
                "Sparkles are **random reactions** that can appear on messages!\n\n"
                "**Types of Sparkles:**\n"
                "✨ **Regular Sparkle** – 1/1,000 chance\n"
                "🌟 **Rare Sparkle** – 1/10,000 chance\n"
                "💫 **Epic Sparkle** – 1/100,000 chance\n\n"
                "Track your sparkles using `/sparkle check` or `/sparkle leaderboard`."
            ),
            color=get_embed_color(interaction.user.id)
        )
        embed.set_footer(text="Keep chatting to test your luck!")
        await interaction.response.send_message(embed=embed)

    # ========== /sparkle leaderboard ==========
    @sparkle_group.command(name="leaderboard", description="Show random sparkle leaderboard")
    @app_commands.describe(limit="Number of users to show (max 20, default 10)")
    async def sparkle_leaderboard(self, interaction: discord.Interaction, limit: int = 10):
        """Show a randomly ordered sparkle leaderboard for current guild members.

        Filters to members currently in the guild (in-memory set) before
        querying to avoid showing data for users who left. Ordered randomly
        (ORDER BY RANDOM()) because a fixed rank ordering would always be the
        same given equal totals.
        """
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        limit = max(1, min(20, limit))
        guild_member_ids = {str(member.id) for member in interaction.guild.members}

        await interaction.response.defer()

        def db_task():
            conn = get_db()
            placeholders = ",".join(["?"] * len(guild_member_ids))
            cursor = conn.execute(
                f"""
                SELECT user_id, epic, rare, regular,
                       (epic + rare + regular) as total
                FROM sparkles
                WHERE server_id = ? AND user_id IN ({placeholders})
                ORDER BY RANDOM() DESC
                LIMIT ?
                """,
                [str(interaction.guild.id), *guild_member_ids, limit]
            )
            rows = cursor.fetchall()
            conn.close()
            return rows

        rows = await asyncio.to_thread(db_task)

        if not rows:
            return await interaction.followup.send(
                "No sparkle data available.",
                ephemeral=True
            )

        embed = discord.Embed(
            title=f"✨ {escape_markdown(interaction.guild.name)} Sparkle Leaderboard",
            color=get_embed_color(interaction.user.id)
        )

        medal = {1: "🥇", 2: "🥈", 3: "🥉"}

        for i, (uid, epic, rare, regular, total) in enumerate(rows, 1):
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"Unknown ({uid})"

            prefix = medal.get(i, f"{i}.")
            embed.add_field(
                name=f"{prefix} {escape_markdown(name)}",
                value=(
                    f"{self.sparkle_emojis['epic']} {epic} | "
                    f"{self.sparkle_emojis['rare']} {rare} | "
                    f"{self.sparkle_emojis['regular']} {regular} | "
                    f"**Total:** {total}"
                ),
                inline=False
            )

            if i == 1 and member:
                embed.set_thumbnail(url=member.display_avatar.url)

        await interaction.followup.send(embed=embed)

    # ========== /sparkle test ==========
    @sparkle_group.command(name="test", description="Force a sparkle type for testing")
    @app_commands.describe(
        message_id="ID of the message to sparkle",
        sparkle_type="The sparkle type to trigger",
        gay="Also trigger a gay sparkle"
    )
    @app_commands.choices(sparkle_type=[
        app_commands.Choice(name="Regular", value="regular"),
        app_commands.Choice(name="Rare", value="rare"),
        app_commands.Choice(name="Epic", value="epic"),
    ])
    async def sparkle_test(self, interaction: discord.Interaction, message_id: str, sparkle_type: app_commands.Choice[str], gay: bool = False):
        if interaction.user.id != 252130669919076352:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        sparkle_cog = self.bot.cogs.get("Sparkle")
        if not sparkle_cog:
            await interaction.response.send_message("Sparkle cog not loaded.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            msg = await interaction.channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.HTTPException, ValueError):
            await interaction.followup.send("Couldn't find that message in this channel.", ephemeral=True)
            return

        await sparkle_cog._add_sparkle(msg, sparkle_type.value, gay, save_to_db=False)
        await interaction.followup.send("Done!", ephemeral=True)

    # ========== /sparkle stats ==========
    @sparkle_group.command(name="stats", description="View server sparkle statistics")
    async def sparkle_stats(self, interaction: discord.Interaction):
        """Show server-wide sparkle totals, message-per-sparkle ratios, and per-type timing.

        Pulls total counts from the sparkles table and timestamped events from
        sparkle_events. Also opens stats.db from a separate connection to read
        the total message count for the messages-per-sparkle calculation.
        """
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        await interaction.response.defer()

        def db_task():
            conn = get_db()
            sid = str(interaction.guild.id)

            # Get all sparkles from sparkles table (historical totals)
            cursor = conn.execute(
                """SELECT COALESCE(SUM(epic), 0), COALESCE(SUM(rare), 0), COALESCE(SUM(regular), 0)
                   FROM sparkles WHERE server_id = ?""",
                (sid,)
            )
            total_epic, total_rare, total_regular = cursor.fetchone()

            # Get sparkle events split by type (for timing data)
            cursor = conn.execute(
                """SELECT sparkle_type, timestamp FROM sparkle_events
                   WHERE server_id = ? ORDER BY timestamp ASC""",
                (sid,)
            )
            all_events = cursor.fetchall()
            conn.close()

            # Separate events per type
            by_type: dict[str, list] = {"epic": [], "rare": [], "regular": []}
            for sparkle_type, ts in all_events:
                if sparkle_type in by_type:
                    by_type[sparkle_type].append(ts)

            # Get total message count from stats.db
            stats_db_path = Path(__file__).parent.parent / "data" / "stats.db"
            total_messages = 0
            try:
                stats_conn = sqlite3.connect(stats_db_path)
                stats_cursor = stats_conn.execute("SELECT SUM(message_count) FROM message_stats")
                result = stats_cursor.fetchone()
                if result and result[0]:
                    total_messages = result[0]
                stats_conn.close()
            except Exception:
                pass

            return total_epic, total_rare, total_regular, all_events, total_messages, by_type

        total_epic, total_rare, total_regular, all_events, total_messages, by_type = await asyncio.to_thread(db_task)

        epic  = total_epic
        rare  = total_rare
        regular = total_regular
        total = epic + rare + regular

        if total == 0:
            return await interaction.followup.send(
                "This server has **no sparkles yet!** ✨",
                ephemeral=True
            )

        def humanize(seconds: float) -> str:
            return str(datetime.timedelta(seconds=int(seconds)))

        embed = discord.Embed(
            title=f"📊 Sparkle Stats for {interaction.guild.name}",
            color=get_embed_color(interaction.user.id)
        )

        embed.add_field(
            name="Totals",
            value=(
                f"💫 **Epic:** {epic}\n"
                f"🌟 **Rare:** {rare}\n"
                f"✨ **Regular:** {regular}\n"
                f"**Total:** {total}"
            ),
            inline=False
        )

        all_timestamps = sorted(ts for events in by_type.values() for ts in events)
        has_event_data = bool(all_timestamps)

        # Combined message stats + timing
        if has_event_data:
            event_count = len(all_timestamps)

            if total_messages > 0:
                embed.add_field(
                    name="Message Statistics",
                    value=f"**Average messages per sparkle:** ~{int(total_messages / event_count):,}",
                    inline=False
                )

            if event_count >= 2:
                deltas = [all_timestamps[i+1] - all_timestamps[i] for i in range(event_count - 1)]
                avg_time = sum(deltas) / len(deltas)
                embed.add_field(
                    name="Timing",
                    value=(
                        f"**Average time between sparkles:** {humanize(avg_time)}\n"
                        f"**Last sparkle:** <t:{int(all_timestamps[-1])}:R>"
                    ),
                    inline=False
                )

        # Per-type breakdown
        for sparkle_type, emoji, label in (
            ("epic",    "💫", "Epic"),
            ("rare",    "🌟", "Rare"),
            ("regular", "✨", "Regular"),
        ):
            timestamps = by_type[sparkle_type]
            if not timestamps:
                continue

            lines = []

            if total_messages > 0:
                lines.append(f"**Avg messages per sparkle:** ~{int(total_messages / len(timestamps)):,}")

            if len(timestamps) >= 2:
                deltas = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps) - 1)]
                lines.append(f"**Avg time between:** {humanize(sum(deltas) / len(deltas))}")

            lines.append(f"**Last sparkle:** <t:{int(timestamps[-1])}:R>")

            embed.add_field(name=f"{emoji} {label}", value="\n".join(lines), inline=False)

        if has_event_data:
            embed.set_footer(text="Message statistics are server-wide. Timing data from logged events.")
        else:
            embed.set_footer(text="All sparkles are from before event logging was added.")

        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(SparkleCommands(bot))
