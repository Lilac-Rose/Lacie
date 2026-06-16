import discord
from discord.ext import commands
from discord.ui import View, Button
import sqlite3
from pathlib import Path
from .loader import ModerationBase

DB_PATH = Path(__file__).parent.parent / "data" / "moderation.db"

# Role ID for the server's muted role — must match mute.py
MUTE_ROLE_ID = 982702037517090836


class UnmuteCommand(ModerationBase):
    """Cog providing the !unmute prefix command.

    Removes the mute role from a member immediately and clears their entry from
    the persistent `mutes` table, preventing `mute.py`'s background task from
    trying to unmute them again when the timer expires.
    """

    @commands.command(name="unmute")
    @ModerationBase.is_admin()
    async def unmute(self, ctx, user: discord.Member):
        """Manually remove a mute from a member with a confirmation prompt.

        Removes the mute role, deletes the DB record so the scheduled unmute
        won't fire again, and sends a DM to the user.

        Parameters
        ----------
        user:
            The server member to unmute.
        """
        view = View(timeout=30)
        confirmed = {"value": False}

        async def yes_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("You can't confirm this action.", ephemeral=True)
                return
            confirmed["value"] = True
            await interaction.response.edit_message(content="✅ Confirmed.", view=None)
            view.stop()

        async def no_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("You can't cancel this action.", ephemeral=True)
                return
            confirmed["value"] = False
            await interaction.response.edit_message(content="❌ Cancelled.", view=None)
            view.stop()

        yes_button = discord.ui.Button(label="Yes", style=discord.ButtonStyle.green)
        no_button = discord.ui.Button(label="No", style=discord.ButtonStyle.red)
        yes_button.callback = yes_callback
        no_button.callback = no_callback
        view.add_item(yes_button)
        view.add_item(no_button)

        await ctx.send(f"Are you sure you want to unmute {user.mention}?", view=view)
        await view.wait()
        if not confirmed["value"]:
            return

        mute_role = ctx.guild.get_role(MUTE_ROLE_ID)
        if not mute_role:
            await ctx.send("Mute role not found in server.")
            return

        if mute_role in user.roles:
            await user.remove_roles(mute_role, reason="Manual unmute issued")

            # Remove from DB so the scheduled unmute task won't fire when the timer expires
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM mutes WHERE user_id = ? AND guild_id = ?", (user.id, ctx.guild.id))
            conn.commit()
            conn.close()

            try:
                await user.send(f"You have been **unmuted** in **{ctx.guild.name}**.")
            except Exception:
                await ctx.send("Could not DM the user.")

            await self.log_infraction(ctx.guild.id, user.id, ctx.author.id, "unmute", "Manual unmute issued")
            await ctx.send(f"{user.mention} has been unmuted.")

            logger = self.bot.get_cog("Logger")
            if logger:
                await logger.log_moderation_action(
                    ctx.guild.id, "unmute", user, ctx.author, "Manual unmute issued"
                )
        else:
            await ctx.send(f"{user.mention} is not currently muted.")


async def setup(bot: commands.Bot):
    await bot.add_cog(UnmuteCommand(bot))
