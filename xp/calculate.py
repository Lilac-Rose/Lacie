"""XP calculation helpers: awarding XP, handling cooldowns, leveling up."""
import discord
from discord import app_commands
from discord.ext import commands, tasks
from .database import get_db
from .utils import xp_for_level, can_get_xp, get_multiplier, load_config
from .groups import xp_group
import time
from embed.embed_color import get_embed_color

class CalculateCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Register this command onto the shared xp group
        xp_group.add_command(app_commands.command(name="calculate", description="Calculate XP needed to reach a target level")(self.calculate))

    @app_commands.describe(
        level="Target level to calculate",
        user="User to check (defaults to you)",
        board_type="Choose which XP board to view"
    )
    @app_commands.choices(board_type=[
        app_commands.Choice(name="Lifetime", value="lifetime"),
        app_commands.Choice(name="Annual", value="annual")
    ])
    async def calculate(
        self,
        interaction: discord.Interaction,
        level: int,
        user: discord.Member = None,
        board_type: app_commands.Choice[str] = None
    ):
        # Immediately defer to prevent timeout
        await interaction.response.defer(thinking=True, ephemeral=False)

        try:
            if user is None:
                user = interaction.user

            # Load config safely
            config = load_config()
            COOLDOWN = config["cooldown"]
            random_xp_config = config["random_xp"]

            # Determine board type
            use_lifetime = True if (board_type is None or board_type.value == "lifetime") else False
            board_name = "Lifetime" if use_lifetime else "Annual"

            # Database query
            conn, cur = get_db(db_type="lifetime")
            cur.execute("SELECT xp, level, last_message FROM xp WHERE user_id = ?", (str(user.id),))
            row = cur.fetchone()
            conn.close()

            if not row:
                await interaction.followup.send(
                    f"{user.mention} has no XP yet on the **{board_name}** board.",
                    ephemeral=True
                )
                return
            
            current_xp, current_level, last_message = row

            if level <= current_level:
                await interaction.followup.send(
                    f"{user.mention} is already level {current_level} on the **{board_name}** board. Please choose a higher target level.",
                    ephemeral=True
                )
                return
            
            target_xp = xp_for_level(level)
            remaining_xp = target_xp - current_xp

            multiplier = get_multiplier(user, apply_multiplier=True)

            min_xp_per_msg = int(random_xp_config["min"] * multiplier)
            max_xp_per_msg = int(random_xp_config["max"] * multiplier)
            avg_xp_per_msg = (min_xp_per_msg + max_xp_per_msg) / 2

            max_messages = int(remaining_xp / min_xp_per_msg)
            min_messages = int(remaining_xp / max_xp_per_msg)
            avg_messages = int(remaining_xp / avg_xp_per_msg)

            time_remaining_seconds = avg_messages * COOLDOWN
            days = time_remaining_seconds / 86400

            progress = (current_xp / target_xp) * 100

            # Progress bar
            bar_length = 30
            filled = int((progress / 100) * bar_length)
            bar = "█" * filled + "░" * (bar_length - filled)

            # Formatting numbers
            current_xp_fmt = f"{current_xp:,}"
            target_xp_fmt = f"{target_xp:,}"
            remaining_xp_fmt = f"{remaining_xp:,}"
            min_messages_fmt = f"{min_messages:,}"
            max_messages_fmt = f"{max_messages:,}"
            avg_messages_fmt = f"{avg_messages:,}"

            # Cooldown info
            time_since_last = time.time() - last_message
            cooldown_ready = can_get_xp(last_message)
            cooldown_status = ""
            if not cooldown_ready:
                cooldown_remaining = COOLDOWN - time_since_last
                cooldown_status = f"\n⏳ Cooldown: {int(cooldown_remaining)}s remaining"

            response = f"""**{board_name} Level {level} Target**
**Current XP:** {current_xp_fmt} (Level {current_level})
**Target XP:** {target_xp_fmt}
**Remaining XP:** {remaining_xp_fmt}

**XP per message:** {min_xp_per_msg} - {max_xp_per_msg}
**Messages remaining:** {min_messages_fmt} - {max_messages_fmt} (avg. {avg_messages_fmt})
**Time remaining:** {days:.1f} days{cooldown_status}

{bar} ({progress:.2f}%)"""

            embed = discord.Embed(description=response, color=get_embed_color(interaction.user.id))
            embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"⚠️ **Error:** {e}", ephemeral=False)

    def cog_unload(self):
        xp_group.remove_command("calculate")

async def setup(bot):
    await bot.add_cog(CalculateCommand(bot))