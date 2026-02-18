"""Chain message event listener (reacts to chain messages in channels)."""
import discord
from discord.ext import commands

class ChainDetector(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Stores per-channel:
        # {channel_id: {"last_message": str, "users": [user_ids]}}
        self.cache = {}
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bot messages
        if message.author.bot:
            return
        
        # Ignore images, stickers, files, etc.
        if message.attachments or message.stickers:
            return
        
        content = message.content.strip()
        if not content:
            return
        
        if message.mentions or message.role_mentions or message.channel_mentions or message.mention_everyone:
            return
        
        channel_id = message.channel.id
        
        # Initialize cache for this channel
        if channel_id not in self.cache:
            self.cache[channel_id] = {
                "last_message": content,
                "users": [message.author.id]
            }
            return
        
        chain = self.cache[channel_id]
        
        # If message matches the chain message
        if content == chain["last_message"]:
            # Only count if it's a DIFFERENT user
            if message.author.id not in chain["users"]:
                chain["users"].append(message.author.id)
        else:
            # Reset chain
            chain["last_message"] = content
            chain["users"] = [message.author.id]
        
        # If three different users said the same thing
        if len(chain["users"]) == 3:
            await message.channel.send(content)
            # Reset the chain completely
            chain["last_message"] = ""
            chain["users"] = []

async def setup(bot):
    await bot.add_cog(ChainDetector(bot))