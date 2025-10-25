import discord
from discord.ext import commands
from discord.ui import View, Button
from .loader import ModerationBase

class BanCommand(ModerationBase):
    @commands.command(name="ban")
    @ModerationBase.is_admin()
    async def ban(self, ctx, user: discord.User | discord.Member | str, *, reason: str = None):
        """Ban a user (even if not in the server) with confirmation and log infraction"""
        # Convert raw ID or mention to user object if needed
        if isinstance(user, str):
            user_id = user.strip("<@!>")
            try:
                user = await self.bot.fetch_user(int(user_id))
            except Exception:
                await ctx.send("Could not find that user. Please provide a valid mention or ID.")
                return

        # Ask for confirmation
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
            f"Are you sure you want to ban {user.mention if hasattr(user, 'mention') else user}? "
            f"Reason: {reason or 'No reason provided'}",
            view=view
        )

        await view.wait()
        if not confirmed["value"]:
            return

        # Attempt to DM user
        try:
            if isinstance(user, discord.User):
                await user.send(
                    f"You have been **banned** from **{ctx.guild.name}**.\n"
                    f"Reason: {reason or 'No reason provided'}\n\n"
                    f"If you believe this ban was unfair, you can appeal by messaging me `!appeal`."
                )
        except:
            await ctx.send("Could not DM the user.")

        # Perform the ban
        try:
            await ctx.guild.ban(discord.Object(id=user.id), reason=reason)
            await ctx.send(f"{user.mention if hasattr(user, 'mention') else user} has been banned.")
        except Exception as e:
            await ctx.send(f"Failed to ban user: `{e}`")
            return

        # Log infraction
        await self.log_infraction(ctx.guild.id, user.id, ctx.author.id, "ban", reason)

        # Log to logging system if available
        logger = self.bot.get_cog("Logger")
        if logger:
            await logger.log_moderation_action(ctx.guild.id, "ban", user, ctx.author, reason)

async def setup(bot: commands.Bot):
    await bot.add_cog(BanCommand(bot))
