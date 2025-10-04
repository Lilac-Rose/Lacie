import discord
from discord.ext import commands
from discord import app_commands
from .database import get_db

class Leaderboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="leaderboard",
        description="Show the server leaderboard"
    )
    @app_commands.describe(
        board_type="Choose which leaderboard to view"
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
        board_type: app_commands.Choice[str] = None
    ):
        # Default to Lifetime
        if board_type is None:
            board_type_value = "lifetime"
            board_display_name = "Lifetime"
        else:
            board_type_value = board_type.value
            board_display_name = board_type.name

        # Determine which database to use
        use_lifetime_db = board_type_value == "lifetime"
        conn, cur = get_db(use_lifetime_db)

        # Fetch top 10 users
        cur.execute("SELECT user_id, xp, level FROM xp ORDER BY xp DESC LIMIT 10")
        rows = cur.fetchall()
        conn.close()

        embed = discord.Embed(
            title=f"{board_display_name} Leaderboard",
            color=discord.Color.blurple()
        )

        if not rows:
            embed.description = "No data available yet!"
        else:
            # Set top user's avatar as thumbnail
            top_user_id = rows[0][0]
            top_user = interaction.guild.get_member(int(top_user_id))
            if top_user:
                embed.set_thumbnail(url=top_user.display_avatar.url)

            for idx, (user_id, xp, level) in enumerate(rows, start=1):
                user = interaction.guild.get_member(int(user_id))
                name = user.display_name if user else f"User {user_id}"
                embed.add_field(
                    name=f"{idx}. {name}",
                    value=f"Level {level} | {xp:,} XP",
                    inline=False
                )

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Leaderboard(bot))
