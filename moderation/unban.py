import discord
from discord.ext import commands
from .loader import ModerationBase

class UnbanCommand(ModerationBase):
    @commands.command(name="unban")
    @ModerationBase.is_admin()
    async def unban(self, ctx, user: discord.User | str, *, reason: str = None):
        """Unban a user by mention, ID, or name."""
        if isinstance(user, str):
            user_id = user.strip("<@!>")
            try:
                user = await self.bot.fetch_user(int(user_id))
            except Exception:
                await ctx.send("Could not find that user. Please provide a valid mention or ID.")
                return

        try:
            await ctx.guild.unban(user, reason=reason)
            await ctx.send(f"✅ {user.mention if hasattr(user, 'mention') else user} has been unbanned.")
        except Exception as e:
            await ctx.send(f"❌ Failed to unban: `{e}`")

        # Log the action
        logger = self.bot.get_cog("Logger")
        if logger:
            await logger.log_moderation_action(ctx.guild.id, "unban", user, ctx.author, reason)


async def setup(bot):
    await bot.add_cog(UnbanCommand(bot))
