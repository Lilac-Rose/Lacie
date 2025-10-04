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

            lines = []
            header = f"{'ID':<8} | {'User':<28} | {'Moderator':<28} | {'Timestamp':<19} | {'Type':<10} | Reason"
            separator = "-" * len(header)
            lines.append(header)
            lines.append(separator)

            for row in results:
                # Fetch user and moderator objects
                user = await self.bot.fetch_user(row["user_id"])
                moderator = await self.bot.fetch_user(row["moderator_id"])

                # Format user and mod names
                user_tag = f"{user.name}#{user.discriminator}"
                mod_tag = f"{moderator.name}#{moderator.discriminator}"

                # Shorten if needed for alignment
                user_tag = user_tag[:27] + "…" if len(user_tag) > 28 else user_tag
                mod_tag = mod_tag[:27] + "…" if len(mod_tag) > 28 else mod_tag

                # Format timestamp
                timestamp = row["timestamp"].replace("T", " ")[:19]

                # Format reason (truncate if too long)
                reason = row["reason"] or "None"

                lines.append(f"{row['id']:<8} | {user_tag:<28} | {mod_tag:<28} | {timestamp:<19} | {row['type']:<10} | {reason}")

            # Send in code block to preserve formatting
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
