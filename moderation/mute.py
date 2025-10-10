import discord
from discord.ext import commands, tasks
from discord.ui import View, Button
import asyncio
import re
import sqlite3
import os
from datetime import timedelta, datetime
from .loader import ModerationBase

MUTE_ROLE_ID = 982702037517090836

class MuteCommand(ModerationBase):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.check_mutes.start()

    def cog_unload(self):
        self.check_mutes.cancel()
        super().cog_unload()

    @commands.command(name="mute")
    @ModerationBase.is_admin()
    async def mute(self, ctx, user: discord.Member, duration: str, *, reason: str = None):
        match = re.match(r"(\d+)([wdhm])", duration.lower())
        if not match:
            await ctx.send("Invalid duration format. Use **1w**, **5d**, **12h**, **30m**, etc.")
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

        db_path = os.path.join(os.path.dirname(__file__), "moderation.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS mutes (
            user_id INTEGER,
            guild_id INTEGER,
            channel_id INTEGER,
            unmute_time TEXT
        )
        """)
        unmute_time = (datetime.utcnow() + delta).isoformat()
        c.execute("INSERT INTO mutes (user_id, guild_id, channel_id, unmute_time) VALUES (?, ?, ?, ?)",
                  (user.id, ctx.guild.id, ctx.channel.id, unmute_time))
        conn.commit()
        conn.close()

        asyncio.create_task(self.schedule_unmute(user.id, ctx.guild.id, ctx.channel.id, delta.total_seconds()))

    async def schedule_unmute(self, user_id, guild_id, channel_id, delay):
        await asyncio.sleep(delay)
        db_path = os.path.join(os.path.dirname(__file__), "moderation.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("DELETE FROM mutes WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        conn.commit()
        conn.close()
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        member = guild.get_member(user_id)
        if not member:
            return
        mute_role = guild.get_role(MUTE_ROLE_ID)
        if not mute_role:
            return
        try:
            await member.remove_roles(mute_role, reason="Mute duration expired")
            channel = guild.get_channel(channel_id)
            if channel:
                await channel.send(f"{member.mention} has been unmuted (duration expired).")
        except:
            pass

    @tasks.loop(minutes=1)
    async def check_mutes(self):
        db_path = os.path.join(os.path.dirname(__file__), "moderation.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        now = datetime.utcnow().isoformat()
        c.execute("SELECT user_id, guild_id, channel_id, unmute_time FROM mutes WHERE unmute_time <= ?", (now,))
        expired = c.fetchall()
        for user_id, guild_id, channel_id, _ in expired:
            asyncio.create_task(self.schedule_unmute(user_id, guild_id, channel_id, 0))
        conn.close()

async def setup(bot: commands.Bot):
    await bot.add_cog(MuteCommand(bot))
