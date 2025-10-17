import discord
from discord import app_commands
from discord.ext import commands
from .database import get_db
from .utils import xp_for_level, can_get_xp, get_multiplier, COOLDOWN
import time

class CalculateCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="calculate", description="Calculate XP needed to reach a target level")
    @app_commands.describe(
        level="Target level to calculate",
        user="User to check (defaults to you)"
    )
    async def calculate(
        self,
        interaction: discord.Interaction,
        level: int,
        user: discord.Member = None
    ):
        if user is None:
            user = interaction.user

        conn, cur = get_db(lifetime=True)
        cur.execute("SELECT xp, level, last_message FROM xp WHERE user_id = ?", (str(user.id),))
        row = cur.fetchone()
        conn.close()

        if not row:
            await interaction.response.send_message(
                f"{user.mention} has no XP yet.",
                ephemeral=True
            )
            return
        
        current_xp, current_level, last_message = row

        if level <= current_level:
            await interaction.response.send_message(
                f"{user.mention} is already level {current_level}. Please choose a higher target level.",
                ephemeral=True
            )
            return
        
        target_xp = xp_for_level(level)
        remaining_xp = target_xp - current_xp

        multiplier = get_multiplier(user, apply_multiplier=True)

        min_xp_per_msg = int(50* multiplier)
        max_xp_per_msg = int(100 * multiplier)
        avg_xp_per_msg = (min_xp_per_msg + max_xp_per_msg) / 2

        max_messages = int(remaining_xp / min_xp_per_msg)
        min_messages = int(remaining_xp / max_xp_per_msg)
        avg_messages = int(remaining_xp / avg_xp_per_msg)

        time_remaining_seconds = avg_messages * COOLDOWN
        days = time_remaining_seconds / 86400

        progress = (current_xp / target_xp) * 100

        bar_length = 30
        filled = int((progress/100) * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)

        current_xp_fmt = f"{current_xp:,}"
        target_xp_fmt = f"{target_xp:,}"
        remaining_xp_fmt = f"{remaining_xp:,}"
        min_messages_fmt = f"{min_messages:,}"
        max_messages_fmt = f"{max_messages:,}"
        avg_messages_fmt = f"{avg_messages:,}"

        time_since_last = time.time() - last_message
        cooldown_ready = can_get_xp(last_message)
        cooldown_status = ""
        if not cooldown_ready:
            cooldown_reamining = COOLDOWN - time_since_last
            cooldown_status = f"\n⏳ Cooldown: {int(cooldown_reamining)}s reamining"

        response = f"""**Level {level} Target**
        **Curent XP:** {current_xp_fmt} (Level {current_level})
        **Target XP:** {target_xp_fmt}
        **Reamining XP:** {remaining_xp_fmt}

        **XP per message:** {min_xp_per_msg} - {max_xp_per_msg}
        **Messages remaining:** {min_messages_fmt} - {max_messages_fmt} (avg. {avg_messages_fmt})
        **Time remaining:** {days:.1f} days{cooldown_status}

        {bar} ({progress:.2f}%)"""

        embed = discord.Embed(
            description=response,
            color=discord.Color.blue()
        )
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(CalculateCommand(bot))