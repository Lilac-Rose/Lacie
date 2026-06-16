import discord
from discord.ext import commands
from .loader import ModerationBase


class UnbanCommand(ModerationBase):
    """Cog providing the !unban prefix command."""

    @commands.command(name="unban")
    @ModerationBase.is_admin()
    async def unban(self, ctx, user: discord.User | str, *, reason: str | None = None):
        """Unban a user by mention, ID, or name.

        Resolves a raw mention or user ID string into a User object if needed,
        then removes the ban and logs the action.

        Parameters
        ----------
        user:
            The user to unban (mention, ID, or User object).
        reason:
            Optional reason for the unban.
        """
        # Resolve a raw ID string or mention into a User object
        if isinstance(user, str):
            user_id = user.strip("<@!>")
            try:
                user = await self.bot.fetch_user(int(user_id))
            except Exception:
                await ctx.send("Could not find that user. Please provide a valid mention or ID.")
                return

        if not ctx.guild:
            return

        try:
            await ctx.guild.unban(user, reason=reason)
            await ctx.send(f"✅ {user.mention if hasattr(user, 'mention') else user} has been unbanned.")
        except Exception as e:
            await ctx.send(f"❌ Failed to unban: `{e}`")
            return

        await self.log_infraction(ctx.guild.id, user.id, ctx.author.id, "unban", reason)

        logger = self.bot.get_cog("Logger")
        if logger:
            await logger.log_moderation_action(ctx.guild.id, "unban", user, ctx.author, reason)


async def setup(bot):
    await bot.add_cog(UnbanCommand(bot))
