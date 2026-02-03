import discord
import time
import math
import traceback
from discord.ext import commands
from discord import app_commands
from .database import get_db
from .utils import xp_for_level, get_multiplier, MULTIPLIERS, COOLDOWN
from .groups import xp_group

class Rank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Register this command onto the shared xp group
        xp_group.add_command(app_commands.command(name="rank", description="Check your rank or another user's rank")(self.rank))

    @app_commands.describe(
        user="The user to check rank for (leave empty for yourself)",
        board_type="Choose which XP board to view"
    )
    @app_commands.choices(board_type=[
        app_commands.Choice(name="Lifetime", value="lifetime"),
        app_commands.Choice(name="Annual", value="annual")
    ])
    async def rank(
        self, 
        interaction: discord.Interaction, 
        user: discord.User = None, 
        board_type: app_commands.Choice[str] = None
    ):
        try:
            # Defer the response immediately to prevent timeout
            await interaction.response.defer()
            
            user = user or interaction.user
            board_type_value = board_type.value if board_type else "lifetime"
            lifetime = board_type_value == "lifetime"

            conn, cur = get_db(board_type_value)

            # Fetch XP data for the requested user
            cur.execute("SELECT xp, level, last_message FROM xp WHERE user_id = ?", (str(user.id),))
            row = cur.fetchone()

            if not row:
                conn.close()
                await interaction.followup.send(f"{user.display_name} has no XP yet.", ephemeral=True)
                return

            xp, level, last_msg = row

            # Determine the user's leaderboard rank (filtering absent users like in leaderboard.py)
            cur.execute("SELECT user_id FROM xp ORDER BY xp DESC")
            all_users = [r[0] for r in cur.fetchall()]
            conn.close()

            # Filter out users who are no longer in the guild
            all_users = [
                uid for uid in all_users
                if interaction.guild.get_member(int(uid)) is not None
            ]

            try:
                rank_position = all_users.index(str(user.id)) + 1
            except ValueError:
                rank_position = None

            total_users = len(all_users)
            rank_text = f"#{rank_position:,} / {total_users:,}" if rank_position else "Unranked"

            # XP and progression
            next_level_xp = xp_for_level(level + 1)
            needed = next_level_xp - xp

            # Cooldown
            remaining_cd = COOLDOWN - (time.time() - last_msg)
            cooldown = f"{int(remaining_cd)}s" if remaining_cd > 0 else "None!"

            multiplier = 1.0
            multipliers_text = []

            # Multiplier text (Lifetime only)
            if lifetime and isinstance(user, discord.Member) and user.guild == interaction.guild:
                multiplier = get_multiplier(user, apply_multiplier=True)
                role_name = None
                for role in user.roles:
                    if role.id in MULTIPLIERS and MULTIPLIERS[role.id] == multiplier:
                        role_name = role.mention
                        break
                multipliers_text.append(f"{role_name} – {multiplier}x XP" if role_name else "None")

            # Progress bar
            percent = (xp - xp_for_level(level)) / (next_level_xp - xp_for_level(level))
            percent = max(0, min(1, percent))
            bar_length = 20
            filled = int(percent * bar_length)
            bar = "█" * filled + "░" * (bar_length - filled)

            # Estimated messages left
            min_msgs = math.ceil(math.ceil(needed / 100) / multiplier)
            max_msgs = math.ceil(math.ceil(needed / 50) / multiplier)

            # Embed
            embed = discord.Embed(
                title=f"{'Lifetime' if lifetime else 'Annual'} XP Rank",
                description=(
                    f"🏅 **Rank:** {rank_text}\n"
                    f"✨ **XP:** `{xp:,}` (lv. {level})\n"
                    f"➡️ **Next level:** `{next_level_xp:,}` ({needed:,} more)\n"
                    f"🕒 **Cooldown:** {cooldown}"
                ),
                color=self.bot.get_cog("EmbedColor").get_user_color(interaction.user)
            )

            if lifetime and multipliers_text:
                embed.description += f"\n\n🌟 **Multiplier**\n" + "\n".join(multipliers_text)

            embed.set_author(name=f"{user.display_name}", icon_url=user.display_avatar.url)
            embed.add_field(
                name=f"{bar} ({percent*100:.2f}%)",
                value=f"{min_msgs}-{max_msgs} messages to go!",
                inline=False
            )

            embed.set_footer(text=f"Viewing {board_type_value.title()} board")

            # Use followup instead of response since we deferred
            await interaction.followup.send(embed=embed)

        except Exception as e:
            print(f"Rank command error: {e}")
            traceback.print_exc()
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "An error occurred while fetching rank data.", ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "An error occurred while fetching rank data.", ephemeral=True
                    )
            except:
                pass

    def cog_unload(self):
        # Remove our command from the group when the cog is unloaded (e.g. on !reload)
        xp_group.remove_command("rank")

async def setup(bot):
    await bot.add_cog(Rank(bot))