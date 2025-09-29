import os
import sqlite3
from discord.ext import commands

ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"))

class ResetAnnual(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="resetannual")
    async def reset_annual(self, ctx):
        if ADMIN_ROLE_ID not in [r.id for r in ctx.author.roles]:
            await ctx.send("You don’t have permission.")
            return
        conn = sqlite3.connect("annual.db")
        cur = conn.cursor()
        cur.execute("DELETE FROM xp")
        conn.commit()
        conn.close()
        await ctx.send("Annual XP leaderboard has been reset.")

async def setup(bot):
    await bot.add_cog(ResetAnnual(bot))
