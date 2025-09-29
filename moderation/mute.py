import discord
from discord.ext import commands, tasks
from .loader import ModerationBase
from discord.ui import View, Button
import asyncio
import re
from datetime import datetime, timedelta

MUTE_ROLE_ID = 982702037517090836

class MuteCommand(ModerationBase):

    @commands.command(name="mute")
    @ModerationBase.is_admin()
    async def mute(self, ctx, user: discord.Member, duration: str, *, reason: str = None):
        """Mute a user for a duration with confirmation and log infraction"""
        # Parse duration
        match = re.match(r"(\d+)([wdh])", duration.lower())
        if not match:
            await ctx.send("Invalid duration format. Use 1w, 5d, 48h etc.")
            return
        value, unit = match.groups()
        value = int(value)
        if unit == "w":
            delta = timedelta(weeks=value)
        elif unit == "d":
            delta = timedelta(days=value)
        elif unit == "h":
            delta = timedelta(hours=value)
        else:
            await ctx.send("Unknown time unit. Use w, d, or h.")
            return

        view = View(timeout=30)
        confirmed = {"value": False}

        async def yes_callback(interaction):
            confirmed["value"] = True
            view.stop()
            await interaction.response.edit_message(content="Confirmed", view=None)

        async def no_callback(interaction):
            confirmed["value"] = False
            view.stop()
            await interaction.response.edit_message(content="Cancelled", view=None)

        view.add_item(Button(label="Yes", style=discord.ButtonStyle.green, custom_id="yes"))
        view.add_item(Button(label="No", style=discord.ButtonStyle.red, custom_id="no"))

        async def button_listener(interaction):
            if interaction.custom_id == "yes":
                await yes_callback(interaction)
            else:
                await no_callback(interaction)

        for item in view.children:
            item.callback = button_listener

        await ctx.send(f"Are you sure you want to mute {user.mention} for {duration}? Reason: {reason}", view=view)
        await view.wait()
        if not confirmed["value"]:
            return

        # Add role
        mute_role = ctx.guild.get_role(MUTE_ROLE_ID)
        if not mute_role:
            await ctx.send("Mute role not found in server.")
            return
        await user.add_roles(mute_role, reason=reason)

        # DM user
        try:
            await user.send(f"You have been muted in {ctx.guild.name} for {duration}. Reason: {reason or 'No reason provided'}")
        except:
            await ctx.send("Could not DM the user.")

        # Log infraction
        await self.log_infraction(ctx.guild.id, user.id, ctx.author.id, "mute", reason)

        await ctx.send(f"{user.mention} has been muted for {duration}")

        # Schedule unmute
        async def unmute_later():
            await asyncio.sleep(delta.total_seconds())
            try:
                await user.remove_roles(mute_role, reason="Mute duration expired")
                await ctx.send(f"{user.mention} has been unmuted (duration expired)")
            except:
                pass

        asyncio.create_task(unmute_later())

async def setup(bot: commands.Bot):
    await bot.add_cog(MuteCommand(bot))