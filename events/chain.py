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

        # Ignore images, files, etc. (but allow stickers)
        if message.attachments:
            return

        if message.mentions or message.role_mentions or message.channel_mentions or message.mention_everyone:
            return

        # Determine chain key and how to send
        if message.stickers:
            sticker = message.stickers[0]
            chain_key = f"sticker:{sticker.id}"
            async def send_chain():
                await message.channel.send(stickers=[sticker])
        else:
            content = message.content.strip()
            if not content:
                return
            chain_key = content
            async def send_chain():
                await message.channel.send(chain_key)

        channel_id = message.channel.id

        # Initialize cache for this channel
        if channel_id not in self.cache:
            self.cache[channel_id] = {
                "last_message": chain_key,
                "users": [message.author.id]
            }
            return

        chain = self.cache[channel_id]

        # If message matches the chain message
        if chain_key == chain["last_message"]:
            # Only count if it's a DIFFERENT user
            if message.author.id not in chain["users"]:
                chain["users"].append(message.author.id)
        else:
            # Reset chain
            chain["last_message"] = chain_key
            chain["users"] = [message.author.id]

        # If three different users said the same thing
        if len(chain["users"]) == 3:
            await send_chain()
            # Reset the chain completely
            chain["last_message"] = ""
            chain["users"] = []

async def setup(bot):
    await bot.add_cog(ChainDetector(bot))