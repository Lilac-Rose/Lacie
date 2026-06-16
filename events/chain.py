import discord
from discord.ext import commands


class ChainDetector(commands.Cog):
    """Cog that detects message chains and mirrors them once a third user joins in.

    A chain is defined as 3 different users in the same channel sending the
    exact same text (or the same sticker). When the third unique participant
    is detected, the bot echoes the message, then resets the chain state so
    subsequent posts don't trigger it again.

    Messages with attachments or any kind of mention (user, role, channel,
    everyone) are excluded to prevent abuse.
    """

    def __init__(self, bot):
        self.bot = bot
        # Stores per-channel state:
        # {channel_id: {"last_message": str, "users": [user_ids]}}
        self.cache = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Track messages for chain detection and echo on the third participant."""
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

        # Initialize cache for this channel on first message
        if channel_id not in self.cache:
            self.cache[channel_id] = {
                "last_message": chain_key,
                "users": [message.author.id]
            }
            return

        chain = self.cache[channel_id]

        if chain_key == chain["last_message"]:
            # Only count if it's a DIFFERENT user — same user repeating doesn't advance the chain
            if message.author.id not in chain["users"]:
                chain["users"].append(message.author.id)
        else:
            # Different message breaks the chain — start fresh
            chain["last_message"] = chain_key
            chain["users"] = [message.author.id]

        # Echo on exactly the third unique participant
        if len(chain["users"]) == 3:
            await send_chain()
            # Reset so a fourth+ message doesn't echo again
            chain["last_message"] = ""
            chain["users"] = []


async def setup(bot):
    await bot.add_cog(ChainDetector(bot))
