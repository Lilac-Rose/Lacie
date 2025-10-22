import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
from .database import get_db
import math

class LeaderboardView(View):
    def __init__(self, embed_pages):
        super().__init__(timeout=60)
        self.embed_pages = embed_pages
        self.current_page = 0

    async def update_message(self, interaction: discord.Interaction):
        embed = self.embed_pages[self.current_page]
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: Button):
        if self.current_page > 0:
            self.current_page -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: Button):
        if self.current_page < len(self.embed_pages) - 1:
            self.current_page += 1
        await self.update_message(interaction)


class Leaderboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="top",
        description="Show the server leaderboard"
    )
    @app_commands.describe(
        board_type="Choose which leaderboard to view",
        show_offline="Show users who aren't in the server"
    )
    @app_commands.choices(
        board_type=[
            app_commands.Choice(name="Lifetime XP", value="lifetime"),
            app_commands.Choice(name="Annual XP", value="annual")
        ]
    )
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        board_type: app_commands.Choice[str] = None,
        show_offline: bool = False
    ):
        board_type_value = board_type.value if board_type else "annual"
        board_display_name = board_type.name if board_type else "Annual"

        use_lifetime_db = board_type_value == "lifetime"
        conn, cur = get_db(use_lifetime_db)

        cur.execute("SELECT user_id, xp, level FROM xp ORDER BY xp DESC")
        all_rows = cur.fetchall()
        conn.close()

        if not all_rows:
            return await interaction.response.send_message("No leaderboard data yet!", ephemeral=True)

        user_id = str(interaction.user.id)

        # Filter rows for non-members if show_offline is False
        if not show_offline:
            all_rows = [
                row for row in all_rows
                if interaction.guild.get_member(int(row[0])) is not None
            ]

        if not all_rows:
            return await interaction.response.send_message(
                "No visible leaderboard entries with the current settings.", ephemeral=True
            )

        per_page = 10
        total_pages = math.ceil(len(all_rows) / per_page)
        embeds = []

        for page_num in range(total_pages):
            start_idx = page_num * per_page
            end_idx = start_idx + per_page
            page_rows = all_rows[start_idx:end_idx]

            embed = discord.Embed(
                title=f"{board_display_name} Leaderboard (Page {page_num + 1}/{total_pages})",
                color=discord.Color.blurple()
            )

            if page_num == 0 and page_rows:
                top_member = interaction.guild.get_member(int(page_rows[0][0]))
                if top_member:
                    embed.set_thumbnail(url=top_member.display_avatar.url)

            description_lines = []
            for idx, (uid, xp, level) in enumerate(page_rows, start=start_idx + 1):
                member = interaction.guild.get_member(int(uid))
                if member:
                    line = f"{idx}. {member.mention} · Level {level} · {xp:,} XP"
                    description_lines.append(line)
                elif show_offline:
                    line = f"{idx}. User {uid} · Level {level} · {xp:,} XP"
                    description_lines.append(line)

            embed.description = "\n".join(description_lines)
            embeds.append(embed)

        view = LeaderboardView(embeds)
        await interaction.response.send_message(embed=embeds[0], view=view)


async def setup(bot):
    await bot.add_cog(Leaderboard(bot))