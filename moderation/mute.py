import discord
from discord.ext import commands
from discord.ui import View, Button
import re
from datetime import datetime, timedelta
from .loader import ModerationBase

MUTE_ROLE_ID = 982702037517090836

class MuteCommand(ModerationBase):
    @commands.command(name="mute")
    @ModerationBase.is_admin()
    async def mute(self, ctx, user: discord.Member, duration: str, *, reason: str = None):
        """Mute a user for a duration with confirmation and log infraction."""
        
        # Parse duration (1w, 5d, 48h, 30m)
        match = re.match(r"(\d+)([wdhm])", duration.lower())
        if not match:
            await ctx.send("Invalid duration format. Use **1w**, **5d**, **48h**, **30m**, etc.")
            return

        value, unit = match.groups()
        value = int(value)

        if unit == "w":
            delta = timedelta(weeks=value)
        elif unit == "d":
            delta = timedelta(days=value)
        elif unit == "h":
            delta = timedelta(hours=value)
        elif unit == "m":
            delta = timedelta(minutes=value)
        else:
            await ctx.send("Invalid time unit. Use w/d/h/m.")
            return

        # Confirmation view
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

        yes_button = Button(label="Yes", style=discord.ButtonStyle.green)
        no_button = Button(label="No", style=discord.ButtonStyle.red)
        yes_button.callback = yes_callback
        no_button.callback = no_callback
        view.add_item(yes_button)
        view.add_item(no_button)

        await ctx.send(
            f"Are you sure you want to mute {user.mention} for **{duration}**? "
            f"Reason: {reason or 'No reason provided'}",
            view=view
        )
        await view.wait()

        if not confirmed["value"]:
            return

        mute_role = ctx.guild.get_role(MUTE_ROLE_ID)
        if not mute_role:
            await ctx.send("Mute role not found in server.")
            return

        # Add mute role
        await user.add_roles(mute_role, reason=reason)

        # Try to DM the user
        try:
            await user.send(
                f"You have been muted in **{ctx.guild.name}** for **{duration}**.\n"
                f"Reason: {reason or 'No reason provided'}"
            )
        except:
            await ctx.send("Could not DM the user.")

        # Log infraction
        await self.log_infraction(ctx.guild.id, user.id, ctx.author.id, "mute", reason)
        
        await ctx.send(f"{user.mention} has been muted for **{duration}**.")

        # Store mute in DB for auto-unmute (fixed to use consistent data types)
        unmute_time = datetime.utcnow() + delta
        try:
            self.c.execute("""
                INSERT OR REPLACE INTO mutes (user_id, guild_id, unmute_time, channel_id)
                VALUES (?, ?, ?, ?)
            """, (user.id, ctx.guild.id, unmute_time.isoformat(), ctx.channel.id))
            self.conn.commit()
            print(f"✅ Stored mute for {user} until {unmute_time.isoformat()}")
        except Exception as e:
            print(f"❌ Failed to insert mute into DB: {e}")
            await ctx.send(f"⚠️ Warning: Auto-unmute may not work. Error: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(MuteCommand(bot))