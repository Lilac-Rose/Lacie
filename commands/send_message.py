import discord
from discord.ext import commands

OWNER_ID = 252130669919076352

class SendMessage(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="sendmessage")
    async def send_message(self, ctx, server_id: int, channel_id: int, *, message: str):
        """Send a message to a specific channel in a specific server (owner only)."""
        if ctx.author.id != OWNER_ID:
            await ctx.send("You do not have permission to use this command.")
            return

        # Try to get the guild (server)
        guild = self.bot.get_guild(server_id)
        if guild is None:
            await ctx.send(f"Could not find server with ID `{server_id}`.")
            return

        # Try to get the channel
        channel = guild.get_channel(channel_id)
        if channel is None:
            await ctx.send(f"Could not find channel with ID `{channel_id}` in that server.")
            return

        try:
            await channel.send(message)
            await ctx.send(f"✅ Message sent to <#{channel_id}> in **{guild.name}**.")
        except discord.Forbidden:
            await ctx.send("❌ I don’t have permission to send messages in that channel.")
        except Exception as e:
            await ctx.send(f"❌ Failed to send message: `{e}`")

async def setup(bot):
    await bot.add_cog(SendMessage(bot))
