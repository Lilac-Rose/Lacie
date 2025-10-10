import discord
from discord.ext import commands
from discord.ui import View, Button
import asyncio
import re
from datetime import timedelta
from .loader import ModerationBase

MUTE_ROLE_ID = 982702037517090836

class MuteCommand(ModerationBase):

    @commands.command(name="mute")
    @ModerationBase.is_admin()
    async def mute(self, ctx, user: discord.Member, duration: str, *, reason: str = None):
        """Mute a user for a duration with confirmation and log infraction"""
        # Parse duration
        match = re.match(r"(\d+)([wdh])", duration.lower())
        if not match:
            await ctx.send("Invalid duration format. Use **1w**, **5d**, **48h**, etc.")
            return

        value, unit = match.groups()
        value = int(value)
        if unit == "w":
            delta = timedelta(weeks=value)
        elif unit == "d":
            delta = timedelta(days=value)
        elif unit == "h":
            delta = timedelta(hours=value)

        view = View(timeout=30)
        confirmed = {"value": False}

        async def yes_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("You can’t confirm this action.", ephemeral=True)
                return
            confirmed["value"] = True
            await interaction.response.edit_message(content="✅ Confirmed.", view=None)
            view.stop()

        async def no_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("You can’t cancel this action.", ephemeral=True)
                return
            confirmed["value"] = False
            await interaction.response.edit_message(content="❌ Cancelled.", view=None)
            view.stop()

        yes_button = Button(label="Yes", style=discord.ButtonStyle.green)
        no_button = Button(label="No", style=discord.ButtonStyle.red)
        yes_button.callback = yes_callback
        no_button.callback = no_callback

        view.add_item(yes_button)
        view.add_item(no_button)

        await ctx.send(f"Are you sure you want to mute {user.mention} for **{duration}**? Reason: {reason or 'No reason provided'}", view=view)
        await view.wait()
        if not confirmed["value"]:
            return

        mute_role = ctx.guild.get_role(MUTE_ROLE_ID)
        if not mute_role:
            await ctx.send("Mute role not found in server.")
            return

        await user.add_roles(mute_role, reason=reason)

        try:
            await user.send(f"You have been muted in **{ctx.guild.name}** for **{duration}**.\nReason: {reason or 'No reason provided'}")
        except:
            await ctx.send("Could not DM the user.")

        await self.log_infraction(ctx.guild.id, user.id, ctx.author.id, "mute", reason)
        await ctx.send(f"{user.mention} has been muted for **{duration}**.")

        # Schedule unmute
        async def unmute_later():
            await asyncio.sleep(delta.total_seconds())
            try:
                await user.remove_roles(mute_role, reason="Mute duration expired")
                await ctx.send(f"{user.mention} has been unmuted (duration expired).")
            except:
                pass

        asyncio.create_task(unmute_later())

async def setup(bot: commands.Bot):
    await bot.add_cog(MuteCommand(bot))
