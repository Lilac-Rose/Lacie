from discord.ext import commands
from .database import get_db
from .odds import get_sparkle_type
import asyncio
import random
import time


class Sparkle(commands.Cog):
    """Cog that randomly awards sparkle reactions to messages.

    Sparkle probability is determined by a random roll on each message:
    - Regular (✨): ~1/1,000
    - Rare    (🌟): ~1/10,000
    - Epic    (💫): ~1/100,000
    - Gay     (<:garkle:>): 1/10 chance whenever any sparkle is awarded

    Both the per-user count and the timestamped event log are updated in the DB
    via asyncio.to_thread to avoid blocking the event loop.
    """

    def __init__(self, bot):
        self.bot = bot
        self.chances = {
            "epic": ("💫", "an **epic sparkle**"),
            "rare": ("🌟", "a **rare sparkle**"),
            "regular": ("✨", "a **regular sparkle**"),
            "gay": ("<:garkle:1533323840145330389>", "a **gay sparkle**")
        }

    async def _add_sparkle(self, message, sparkle_type, is_gay=False, save_to_db=True):
        """React to the message and update both the sparkle counter and event log in the DB."""
        emoji, description = self.chances[sparkle_type]
        gay_emoji, gay_description = self.chances["gay"]

        # Add reaction(s) and send notification
        await message.add_reaction(emoji)
        if is_gay:
            await message.add_reaction(gay_emoji)
            await message.reply(
                f"**{message.author.name}** got {description} and {gay_description}! {emoji} {gay_emoji}",
                mention_author=False
            )
        else:
            await message.reply(
                f"**{message.author.name}** got {description}! {emoji}",
                mention_author=False
            )

        if not save_to_db:
            return

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
        sparkle_type = get_sparkle_type(message.id, message.author.id)
        if sparkle_type:
            is_gay = random.randint(1, 10) == 1
            await self._add_sparkle(message, sparkle_type, is_gay)


async def setup(bot):
    await bot.add_cog(Sparkle(bot))