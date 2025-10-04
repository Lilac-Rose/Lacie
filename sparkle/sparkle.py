import random
import discord
from discord.ext import commands
from .database import get_db
import asyncio

class Sparkle(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Updated emoji mapping
        self.chances = {
            "epic": (100000, "💫", "an **epic sparkle**"),
            "rare": (10000, "🌟", "a **rare sparkle**"),
            "regular": (1000, "✨", "a **regular sparkle**")
        }

    async def _add_sparkle(self, message, sparkle_type):
        emoji, description = self.chances[sparkle_type][1:]
        await message.add_reaction(emoji)
        await message.reply(
            f"**{message.author.name}** got {description}! {emoji}",
            mention_author=False
        )

        def db_task():
            conn = get_db()
            conn.execute(
                f"""INSERT INTO sparkles (server_id, user_id, {sparkle_type})
                    VALUES (?, ?, 1)
                    ON CONFLICT(server_id, user_id) DO UPDATE SET
                    {sparkle_type} = {sparkle_type} + 1""",
                (str(message.guild.id), str(message.author.id))
            )
            conn.commit()
            conn.close()

        await asyncio.to_thread(db_task)

    # Percentage bug found and fixed by Alyaunderstars
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        chance = random.randint(1, 1000000)
        if chance == 1:
            await self._add_sparkle(message, "epic")
        elif chance <= 10:
            await self._add_sparkle(message, "rare")
        elif chance <= 1000:
            await self._add_sparkle(message, "regular")

async def setup(bot):
    await bot.add_cog(Sparkle(bot))
