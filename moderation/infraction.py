import discord
from discord.ext import commands
from .loader import ModerationBase
from datetime import datetime

class InfractionCommand(ModerationBase):

    @commands.command(name="inf")
    @ModerationBase.is_admin()
    async def inf(self, ctx, action: str, user_id: int = None, inf_id: int = None):
        if action.lower() == "search":
            if not user_id:
                await ctx.send("You must provide a user ID to search.")
                return

            try:
                self.c.execute("""
                    SELECT id, user_id, type, reason, moderator_id, timestamp
                    FROM infractions
                    WHERE user_id=? AND guild_id=?
                    ORDER BY timestamp DESC
                """, (user_id, ctx.guild.id))
                results = self.c.fetchall()
            except Exception as e:
                await ctx.send(f"Database error: {e}")
                return

        elif action.lower() == "list":
            # Fetch all infractions for the guild
            try:
                self.c.execute("""
                    SELECT id, user_id, type, reason, moderator_id, timestamp
                    FROM infractions
                    WHERE guild_id=?
                    ORDER BY timestamp DESC
                """, (ctx.guild.id,))
                results = self.c.fetchall()
            except Exception as e:
                await ctx.send(f"Database error: {e}")
                return

            if not results:
                await ctx.send("No infractions found in this server.")
                return

        elif action.lower() == "delete":
            if not inf_id:
                await ctx.send("You must provide an infraction ID to delete.")
                return

            self.c.execute("DELETE FROM infractions WHERE id=? AND guild_id=?", (inf_id, ctx.guild.id))
            self.conn.commit()
            await ctx.send(f"Infraction {inf_id} deleted.")
            return

        else:
            await ctx.send("Unknown action. Use search, list, or delete.")
            return

        # Cache users to avoid repeated API calls
        ids_to_cache = set(row[1] for row in results) | set(row[4] for row in results)
        user_cache = {u.id: u for u in self.bot.users if u.id in ids_to_cache}

        # Build rows
        rows = []
        for row in results:
            try:
                user = user_cache.get(row[1]) or await self.bot.fetch_user(int(row[1]))
                moderator = user_cache.get(row[4]) or await self.bot.fetch_user(int(row[4]))
                user_cache[user.id] = user
                user_cache[moderator.id] = moderator
            except Exception as e:
                await ctx.send(f"User fetch error: {e}")
                return

            user_tag = f"{user.name}#{user.discriminator}"
            mod_tag = f"{moderator.name}#{moderator.discriminator}"
            timestamp = row[5].replace("T", " ")[:19]
            reason = row[3] or "None"

            rows.append({
                "id": str(row[0]),
                "user": user_tag,
                "moderator": mod_tag,
                "timestamp": timestamp,
                "type": row[2],
                "reason": reason
            })

        # Prepare table
        widths = {key: max(len(key), *(len(r[key]) for r in rows)) for key in rows[0].keys()}
        header = " | ".join(f"{key.capitalize():{widths[key]}}" for key in rows[0].keys())
        separator = "-" * len(header)

        # Build pages
        chunk_size = 1800
        pages = []
        current_chunk = [header, separator]
        char_count = len("```md\n") + len(header) + len(separator) + 2

        for r in rows:
            line = " | ".join(f"{r[key]:{widths[key]}}" for key in r.keys())
            line_len = len(line) + 1
            if char_count + line_len > chunk_size:
                pages.append("```md\n" + "\n".join(current_chunk) + "\n```")
                current_chunk = [header, separator]
                char_count = len("```md\n") + len(header) + len(separator) + 2
            current_chunk.append(line)
            char_count += line_len

        if current_chunk:
            pages.append("```md\n" + "\n".join(current_chunk) + "\n```")

        # Pagination with buttons
        class PageView(discord.ui.View):
            def __init__(self, pages):
                super().__init__(timeout=180)
                self.pages = pages
                self.current = 0

            async def update_message(self, interaction):
                await interaction.response.edit_message(content=self.pages[self.current], view=self)

            @discord.ui.button(label="Previous", style=discord.ButtonStyle.blurple)
            async def previous(self, button: discord.ui.Button, interaction: discord.Interaction):
                self.current = (self.current - 1) % len(self.pages)
                await self.update_message(interaction)

            @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
            async def next(self, button: discord.ui.Button, interaction: discord.Interaction):
                self.current = (self.current + 1) % len(self.pages)
                await self.update_message(interaction)

        await ctx.send(content=pages[0], view=PageView(pages))


async def setup(bot: commands.Bot):
    await bot.add_cog(InfractionCommand(bot))
