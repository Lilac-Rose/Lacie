import discord
from discord.ext import commands
from discord.ui import View, Button
from .loader import ModerationBase

class KickCommand(ModerationBase):

    @commands.command(name="kick")
    @ModerationBase.is_admin()
    async def kick(self, ctx, user: discord.Member, *, reason: str = None):
        """Kick a user with confirmation and log infraction"""
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

        await ctx.send(f"Are you sure you want to kick {user.mention}? Reason: {reason or 'No reason provided'}", view=view)
        await view.wait()
        if not confirmed["value"]:
            return

        try:
            await user.send(f"You have been **kicked** from **{ctx.guild.name}**.\nReason: {reason or 'No reason provided'}")
        except:
            await ctx.send("Could not DM the user.")

        await ctx.guild.kick(user, reason=reason)
        await ctx.send(f"{user.mention} has been kicked.")
        await self.log_infraction(ctx.guild.id, user.id, ctx.author.id, "kick", reason)

async def setup(bot: commands.Bot):
    await bot.add_cog(KickCommand(bot))
