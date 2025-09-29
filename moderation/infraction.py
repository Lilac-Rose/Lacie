import discord
from discord.ext import commands
from .loader import ModerationBase

class InfractionCommand(ModerationBase):

    @commands.command(name="inf")
    @ModerationBase.is_admin()
    async def inf(self, ctx, action: str, user_id: int = None, inf_id: int = None):
        """?inf search <UserID> or ?inf delete <InfractionID>"""
        if action.lower() == "search":
            if not user_id:
                await ctx.send("You must provide a user ID to search.")
                return
            self.c.execute("""
                SELECT id, type, reason, moderator_id, timestamp
                FROM infractions
                WHERE user_id=? AND guild_id=?
                ORDER BY timestamp DESC
            """, (user_id, ctx.guild.id))
            results = self.c.fetchall()
            if not results:
                await ctx.send("No infractions found.")
                return
            lines = []
            for row in results:
                lines.append(f"ID {row['id']}: {row['type']} by {row['moderator_id']} at {row['timestamp']} - Reason: {row['reason']}")
            await ctx.send("Infractions:\n" + "\n".join(lines))

        elif action.lower() == "delete":
            if not inf_id:
                await ctx.send("You must provide an infraction ID to delete.")
                return
            self.c.execute("DELETE FROM infractions WHERE id=? AND guild_id=?", (inf_id, ctx.guild.id))
            self.conn.commit()
            await ctx.send(f"Infraction {inf_id} deleted.")

async def setup(bot: commands.Bot):
    await bot.add_cog(InfractionCommand(bot))
