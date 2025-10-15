import discord
from discord.ext import commands
import json
import os
from dotenv import load_dotenv

load_dotenv()
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"))

EXCLUDED_FILE = os.path.join(os.path.dirname(__file__), "excluded_channels.json")

def load_excluded_channels():
    """Load excluded channel IDs from JSON file."""
    if not os.path.exists(EXCLUDED_FILE):
        return[]
    with open(EXCLUDED_FILE, "r") as f:
        return json.load(f)
    
def save_excluded_channels(channels):
    """Save excluded channel IDs to JSON file."""
    with open(EXCLUDED_FILE, "w") as f:
        json.dump(channels, f, indent=4)

def add_excluded_channel(channel_id: int):
    """Add a channel to the exclusion list."""
    channels = load_excluded_channels()
    if channel_id not in channels:
        channels.append(channel_id)
        save_excluded_channels(channels)
        return True
    return False

def remove_excluded_channel(channel_id: int):
    """Remove a channel from the exclusion list."""
    channels = load_excluded_channels()
    if channel_id in channels:
        channels.remove(channel_id)
        save_excluded_channels(channels)
        return True
    return False

def is_channel_excluded(channel_id: int) -> bool:
    """Check if a channel is excluded"""
    return channel_id in load_excluded_channels()

class ExcludeChannel(commands.Cog):
    """Commands to manage XP exclusion channels"""
    
    def __init__(self, bot):
        self.bot = bot

    def is_admin(self, member):
        return any(role.id == ADMIN_ROLE_ID for role in member.roles)
    
    @commands.command(name="excludechannel")
    async def exclude_channel(self, ctx, channel: discord.TextChannel = None):
        """Exclude a channel from XP gain."""
        if not self.is_admin(ctx.author):
            return await ctx.send("You do not have permission to use this command.")
        
        if not channel:
            return await ctx.send("Please specify a channel, e.g. '!excludechannel #chat'")
        
        if add_excluded_channel(channel.id):
            await ctx.send(f"{channel.mention} has been excluded from XP gain.")
        else:
            await ctx.send(f"{channel.mention} is already excluded.")

    @commands.command(name="includechannel")
    async def include_channel(self, ctx, channel: discord.TextChannel = None):
        """Remove a channel from the XP exclusion list."""
        if not self.is_admin(ctx.author):
            return await ctx.send("You do not have permission to use this command.")
        
        if not channel:
            return await ctx.send("Please specify a channel, e.g. '!includechannel #chat")
        
        if remove_excluded_channel(channel.id):
            await ctx.send(f"{channel.mention} has been re-enabled for XP gain.")
        else:
            await ctx.send(f"{channel.mention} wasn't excluded.")

    @commands.command(name="excludedlist")
    async def excluded_list(self, ctx):
        """List all channels currently excluded from XP gain."""
        excluded = load_excluded_channels()
        if not excluded:
            return await ctx.send("No channels are currently excluded.")
        channels = [f"<#{cid}>" for cid in excluded]
        await ctx.send("**Excluded Channels:**\n" + "\n".join(channels))


async def setup(bot):
    await bot.add_cog(ExcludeChannel(bot))