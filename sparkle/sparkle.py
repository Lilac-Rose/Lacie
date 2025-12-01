from discord.ext import commands
from .database import get_db
import asyncio
import time


class Sparkle(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.chances = {
            "epic": (100000, "💫", "an **epic sparkle**"),
            "rare": (10000, "🌟", "a **rare sparkle**"),
            "regular": (1000, "✨", "a **regular sparkle**")
        }

    async def _add_sparkle(self, message, sparkle_type):
        """Add a sparkle reaction and update the database."""
        emoji, description = self.chances[sparkle_type][1:]
        
        # Add reaction and send notification
        await message.add_reaction(emoji)
        await message.reply(
            f"**{message.author.name}** got {description}! {emoji}",
            mention_author=False
        )

        # Update database
        def db_task():
            conn = get_db()
            
            # Update per-user sparkle count
            conn.execute(
                f"""INSERT INTO sparkles (server_id, user_id, {sparkle_type})
                    VALUES (?, ?, 1)
                    ON CONFLICT(server_id, user_id) DO UPDATE SET
                    {sparkle_type} = {sparkle_type} + 1""",
                (str(message.guild.id), str(message.author.id))
            )
            
            # Log sparkle event
            conn.execute(
                """INSERT INTO sparkle_events
                   (server_id, user_id, sparkle_type, message_id, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    str(message.guild.id),
                    str(message.author.id),
                    sparkle_type,
                    str(message.id),
                    int(time.time())
                )
            )
            
            conn.commit()
            conn.close()

        await asyncio.to_thread(db_task)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for messages and randomly add sparkles based on message ID."""
        # Ignore bot messages and DMs
        if message.author.bot or not message.guild:
            return
        
        # Check message ID for sparkle probability
        msg_id_str = str(message.id)
        
        if msg_id_str.endswith("00000"):
            await self._add_sparkle(message, "epic")
        elif msg_id_str.endswith("0000"):
            await self._add_sparkle(message, "rare")
        elif msg_id_str.endswith("000"):
            await self._add_sparkle(message, "regular")


async def setup(bot):
    await bot.add_cog(Sparkle(bot))