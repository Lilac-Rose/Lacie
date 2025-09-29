import discord
from discord.ext import commands
from .loader import ModerationBase
from discord.ui import View, Button

class KickCommand(ModerationBase):

    @commands.command(name="kick")
    @ModerationBase.is_admin()
    async def kick(self, ctx, user: discord.Member, *, reason: str = None):
        """Kick a user with confirmation and log infraction"""
        view = View(timeout=30)
        confirmed = {"value": False}

        async def yes_callback(interaction):
            confirmed["value"] = True
            view.stop()
            await interaction.response.edit_message(content="Confirmed.", view=None)

        async def no_callback(interaction):
            confirmed["value"] = False
            view.stop()
            await interaction.response.edit_message(content="Cancelled.", view=None)

        view.add_item(Button(label="Yes", style=discord.ButtonStyle.green, custom_id="yes"))
        view.add_item(Button(label="No", style=discord.ButtonStyle.red, custom_id="no"))

        async def button_listener(interaction):
            if interaction.custom_id == "yes":
                await yes_callback(interaction)
            else:
                await no_callback(interaction)

        for item in view.children:
            item.callback = button_listener

        await ctx.send(f"Are you sure you want to kick {user.mention}? Reason: {reason}", view=view)
        await view.wait()
        if not confirmed["value"]:
            return

        # DM user
        try:
            await user.send(f"You have been **kicked** from {ctx.guild.name}. Reason: {reason or 'No reason provided'}")
        except:
            await ctx.send("Could not DM the user.")

        # Kick
        await ctx.guild.kick(user, reason=reason)
        await ctx.send(f"{user.mention} has been kicked.")

        # Log infraction
        await self.log_infraction(ctx.guild.id, user.id, ctx.author.id, "kick", reason)

async def setup(bot: commands.Bot):
    await bot.add_cog(KickCommand(bot))
