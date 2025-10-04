import discord
import time
import math
import traceback
from discord.ext import commands
from discord import app_commands
from .database import get_db
from .utils import xp_for_level, MULTIPLIERS, COOLDOWN, get_multiplier

class Rank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="rank", description="Check your rank or another user's rank")
    @app_commands.describe(user="The user to check rank for (leave empty for yourself)")
    async def rank(self, interaction: discord.Interaction, user: discord.User = None):
        try:
            user = user or interaction.user

            conn, cur = get_db(True)
            cur.execute("SELECT xp, level, last_message FROM xp WHERE user_id = ?", (str(user.id),))
            row = cur.fetchone()
            conn.close()

            if not row:
                await interaction.response.send_message(f"{user.display_name} has no XP yet.", ephemeral=True)
                return

            xp, level, last_msg = row
            next_level_xp = xp_for_level(level + 1)
            needed = next_level_xp - xp

            # cooldown
            remaining_cd = COOLDOWN - (time.time() - last_msg)
            cooldown = f"{int(remaining_cd)}s" if remaining_cd > 0 else "None!"

            multipliers_text = []
            if isinstance(user, discord.Member) and user.guild == interaction.guild:
                multiplier = get_multiplier(user)
                role_name = None
                for role in user.roles:
                    if str(role.id) in MULTIPLIERS and MULTIPLIERS[str(role.id)] == multiplier:
                        role_name = role.mention
                        break
                if role_name:
                    multipliers_text.append(f"{role_name} – {multiplier}x XP")
                else:
                    multipliers_text.append("None")
            else:
                multipliers_text.append("None")

            # progress bar
            percent = (xp - xp_for_level(level)) / (next_level_xp - xp_for_level(level))
            percent = max(0, min(1, percent))
            bar_length = 20
            filled = int(percent * bar_length)
            bar = "█" * filled + "░" * (bar_length - filled)

            # estimate messages left
            min_msgs = math.ceil(needed / 100)
            max_msgs = math.ceil(needed / 50)

            embed = discord.Embed(
                description=f"✨ **XP** `{xp:,}` (lv. {level})\n"
                            f"➡️ **Next level** `{next_level_xp:,}` ({needed:,} more)\n"
                            f"🕒 **Cooldown** {cooldown}\n\n"
                            f"🌟 **Multiplier**\n" + "\n".join(multipliers_text),
                color=discord.Color.purple()
            )
            embed.set_author(name=f"{user.display_name}", icon_url=user.display_avatar.url)
            embed.add_field(name=f"{bar} ({percent*100:.2f}%)",
                            value=f"{min_msgs}-{max_msgs} messages to go!",
                            inline=False)

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            print(f"Rank command error: {e}")
            traceback.print_exc()
            await interaction.response.send_message("An error occurred while fetching rank data.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Rank(bot))
