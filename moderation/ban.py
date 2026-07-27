import discord
from discord.ext import commands
from discord.ui import View, Button
from .loader import ModerationBase


class BanCommand(ModerationBase):
    """Cog providing the !ban prefix command."""

    @commands.command(name="ban")
    @ModerationBase.is_senior_admin()
    async def ban(self, ctx, user: discord.User | discord.Member | str, *, reason: str | None = None):
        """Ban a user from the server with a confirmation prompt.

        The user does not need to be in the server — a raw user ID or
        mention also works. A DM is sent to the user before banning and
        an infraction record is written to the database.

        Parameters
        ----------
        user:
            The user to ban (mention, ID, or User/Member object).
        reason:
            Optional reason for the ban.
        """
        # Resolve a raw ID string or mention into a User object
        if isinstance(user, str):
            user_id = user.strip("<@!>")
            try:
                user = await self.bot.fetch_user(int(user_id))
            except Exception:
                await ctx.send("Could not find that user. Please provide a valid mention or ID.")
                return

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

        user_ref = user.mention if hasattr(user, "mention") else str(user)
        await ctx.send(
            f"Are you sure you want to ban {user_ref}? "
            f"Reason: {reason or 'No reason provided'}",
            view=view
        )

        await view.wait()
        if not confirmed["value"]:
            return

        if not ctx.guild:
            return

        # Attempt to DM the user before banning so they can still receive the message
        try:
            await user.send(
                f"You have been **banned** from **{ctx.guild.name}**.\n"
                f"Reason: {reason or 'No reason provided'}\n\n"
                f"If you believe this ban was unfair and would like to appeal, join here: https://discord.gg/FYpfBzpjvq"
            )
        except Exception:
            await ctx.send("Could not DM the user.")

        try:
            await ctx.guild.ban(discord.Object(id=user.id), reason=reason)
            await ctx.send(f"{user_ref} has been banned.")
        except Exception as e:
            await ctx.send(f"Failed to ban user: `{e}`")
            return

        await self.log_infraction(ctx.guild.id, user.id, ctx.author.id, "ban", reason)

        logger = self.bot.get_cog("Logger")
        if logger:
            await logger.log_moderation_action(ctx.guild.id, "ban", user, ctx.author, reason)


async def setup(bot: commands.Bot):
    await bot.add_cog(BanCommand(bot))
