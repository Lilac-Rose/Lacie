import discord
from discord.ext import commands
from .loader import ModerationBase
from datetime import datetime

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
                SELECT id, user_id, type, reason, moderator_id, timestamp
                FROM infractions
                WHERE user_id=? AND guild_id=?
                ORDER BY timestamp DESC
            """, (user_id, ctx.guild.id))
            results = self.c.fetchall()

            if not results:
                await ctx.send("No infractions found for that user.")
                return

            # Fetch user/mod info and prepare table rows
            rows = []
            for row in results:
                user = await self.bot.fetch_user(row["user_id"])
                moderator = await self.bot.fetch_user(row["moderator_id"])

                user_tag = f"{user.name}#{user.discriminator}"
                mod_tag = f"{moderator.name}#{moderator.discriminator}"
                timestamp = row["timestamp"].replace("T", " ")[:19]
                reason = row["reason"] or "None"

                rows.append({
                    "id": str(row["id"]),
                    "user": user_tag,
                    "moderator": mod_tag,
                    "timestamp": timestamp,
                    "type": row["type"],
                    "reason": reason
                })

            # Determine max widths dynamically
            widths = {key: max(len(key), *(len(r[key]) for r in rows)) for key in rows[0].keys()}

            # Build header
            header = " | ".join(f"{key.capitalize():{widths[key]}}" for key in rows[0].keys())
            separator = "-" * len(header)

            lines = [header, separator]

            # Build rows
            for r in rows:
                line = " | ".join(f"{r[key]:{widths[key]}}" for key in r.keys())
                lines.append(line)

            table = "```\n" + "\n".join(lines) + "\n```"
            await ctx.send(table)

        elif action.lower() == "delete":
            if not inf_id:
                await ctx.send("You must provide an infraction ID to delete.")
                return

            self.c.execute("DELETE FROM infractions WHERE id=? AND guild_id=?", (inf_id, ctx.guild.id))
            self.conn.commit()
            await ctx.send(f"Infraction {inf_id} deleted.")

async def setup(bot: commands.Bot):
    await bot.add_cog(InfractionCommand(bot))
