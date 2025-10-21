import discord
from discord.ext import commands
from discord import app_commands
from .database import get_db
import asyncio

class Sparkles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sparkle_emojis = {
            "epic": "💫",
            "rare": "🌟",
            "regular": "✨"
        }

    @app_commands.command(name="sparkles", description="Check your sparkle count or another user's")
    @app_commands.describe(user="The user to check sparkle count for (leave empty for yourself)")
    async def sparkles(self, interaction:discord.Interaction, user: discord.User= None):
        user= user or interaction.user

        def db_task():
            conn = get_db()
            cursor = conn.execute(
                """
                SELECT epic, rare, regular,
                    (epic + rare + regular) as total
                FROM sparkles
                WHERE server_id = ? AND user_id = ?
                """,
                (str(interaction.guild.id), str(user.id))
            )
            result = cursor.fetchone()
            conn.close()
            return result
        
        result = await asyncio.to_thread(db_task)

        if not result:
            await interaction.response.send_message(f"{user.display_name} has no sparkles yet!", ephemeral=True)
            return
        
        epic, rare, regular, total = result

        embed = discord.Embed(
            title=f"{user.display_name}'s Sparkles",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(
            name="Totals",
            value=(
                f"{self.sparkle_emojis['epic']} **Epic:** {epic}\n"
                f"{self.sparkle_emojis['rare']} **Rare:** {rare}\n"
                f"{self.sparkle_emojis['regular']} **Regular:** {regular}\n"
                f"**Total:** {total}"
            ),
            inline=False
        )

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Sparkles(bot))