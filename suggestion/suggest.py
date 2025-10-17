import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
from datetime import datetime
import os

ADMIN_ID = 252130669919076352

class Suggestion(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = os.path.join(os.path.dirname(__file__), "suggestions.db")

    async def cog_load(self):
        self.db = await aiosqlite.connect(self.db_path)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                suggestion TEXT,
                status TEXT,
                channel_id INTEGER
            )
        """)
        await self.db.commit()

    async def cog_unload(self):
        await self.db.close()

    @app_commands.command(name="suggest", description="Submit a suggestion")
    async def suggest(self, interaction: discord.Interaction, idea: str):
        try:
            # Insert suggestion into DB first
            await self.db.execute(
                "INSERT INTO suggestions (user_id, suggestion, status, channel_id) VALUES (?, ?, ?, ?)",
                (interaction.user.id, idea, "Pending", interaction.channel_id)
            )
            await self.db.commit()

            async with self.db.execute("SELECT last_insert_rowid()") as cursor:
                suggestion_id = (await cursor.fetchone())[0]

            # Respond to interaction immediately
            await interaction.response.send_message(
                f"✅ Suggestion submitted! (ID: **{suggestion_id}**)\n> {idea}"
            )

            # Send DM to admin in background
            try:
                admin = await self.bot.fetch_user(ADMIN_ID)
                embed = discord.Embed(
                    title=f"New Suggestion (ID: {suggestion_id})",
                    description=idea,
                    color=discord.Color.blurple(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Suggested by", value=f"{interaction.user} ({interaction.user.id})")
                embed.add_field(name="Channel", value=f"<#{interaction.channel_id}>")

                view = SuggestionButtons(self.bot, suggestion_id, interaction.user.id, idea, interaction.channel_id)
                await admin.send(embed=embed, view=view)
            except Exception as e:
                print(f"Failed to send DM to admin: {e}")
                
        except Exception as e:
            print(f"Error in suggest command: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ An error occurred: {e}", ephemeral=False)
            else:
                await interaction.followup.send(f"❌ An error occurred: {e}", ephemeral=False)


    @app_commands.command(name="suggestion_complete", description="Mark an approved suggestion as completed")
    async def suggestion_complete(self, interaction: discord.Interaction, suggestion_id: int):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message("❌ You don't have permission to do that.", ephemeral=True)
            return

        async with self.db.execute(
            "SELECT user_id, suggestion, status, channel_id FROM suggestions WHERE id = ?", (suggestion_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            await interaction.response.send_message("❌ Suggestion not found.", ephemeral=True)
            return

        user_id, suggestion_text, status, channel_id = row
        if status != "Approved":
            await interaction.response.send_message("⚠️ This suggestion must be approved before marking as complete.", ephemeral=True)
            return

        await self.db.execute("UPDATE suggestions SET status = ? WHERE id = ?", ("Completed", suggestion_id))
        await self.db.commit()

        await interaction.response.send_message(f"✅ Suggestion #{suggestion_id} marked as completed!", ephemeral=False)

        # Notify user
        try:
            user = await self.bot.fetch_user(user_id)
            await user.send(f"🎉 Your suggestion (ID: {suggestion_id}) — `{suggestion_text}` has been **implemented!**")
        except:
            pass

        # Notify original channel
        channel = self.bot.get_channel(channel_id)
        if channel:
            await channel.send(f"🎉 Suggestion **#{suggestion_id}** (`{suggestion_text}`) has been marked as **completed!**")


    @app_commands.command(name="suggestion_list", description="List all suggestions (admin only)")
    async def suggestion_list(self, interaction: discord.Interaction):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message("❌ You don't have permission to view this.", ephemeral=True)
            return

        async with self.db.execute("SELECT id, user_id, suggestion, status FROM suggestions ORDER BY id DESC") as cursor:
            rows = await cursor.fetchall()

        if not rows:
            await interaction.response.send_message("No suggestions found.", ephemeral=True)
            return

        embed = discord.Embed(title="📋 Suggestions", color=discord.Color.green())
        for sid, uid, suggestion, status in rows:
            embed.add_field(
                name=f"ID: {sid} | Status: {status}",
                value=f"<@{uid}> — {suggestion[:100]}{'...' if len(suggestion) > 100 else ''}",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


class SuggestionButtons(discord.ui.View):
    def __init__(self, bot, suggestion_id, user_id, suggestion_text, channel_id):
        super().__init__(timeout=None)  # Buttons never expire
        self.bot = bot
        self.suggestion_id = suggestion_id
        self.user_id = user_id
        self.suggestion_text = suggestion_text
        self.channel_id = channel_id

    @discord.ui.button(label="Approve ✅", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message("❌ You can't approve suggestions.", ephemeral=True)
            return

        db_path = os.path.join(os.path.dirname(__file__), "suggestions.db")
        async with aiosqlite.connect(db_path) as db:
            await db.execute("UPDATE suggestions SET status = ? WHERE id = ?", ("Approved", self.suggestion_id))
            await db.commit()

        await interaction.response.send_message(f"✅ Suggestion #{self.suggestion_id} approved.", ephemeral=False)

        try:
            user = await self.bot.fetch_user(self.user_id)
            await user.send(f"✅ Your suggestion (ID: {self.suggestion_id}) — `{self.suggestion_text}` has been **approved!**")
        except:
            pass

        channel = self.bot.get_channel(self.channel_id)
        if channel:
            await channel.send(f"✅ Suggestion **#{self.suggestion_id}** (`{self.suggestion_text}`) has been **approved!**")

        # Disable buttons after action
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

    @discord.ui.button(label="Deny ❌", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message("❌ You can't deny suggestions.", ephemeral=True)
            return

        db_path = os.path.join(os.path.dirname(__file__), "suggestions.db")
        async with aiosqlite.connect(db_path) as db:
            await db.execute("UPDATE suggestions SET status = ? WHERE id = ?", ("Denied", self.suggestion_id))
            await db.commit()

        await interaction.response.send_message(f"❌ Suggestion #{self.suggestion_id} denied.", ephemeral=False)

        try:
            user = await self.bot.fetch_user(self.user_id)
            await user.send(f"❌ Your suggestion (ID: {self.suggestion_id}) — `{self.suggestion_text}` has been **denied.**")
        except:
            pass

        channel = self.bot.get_channel(self.channel_id)
        if channel:
            await channel.send(f"❌ Suggestion **#{self.suggestion_id}** (`{self.suggestion_text}`) has been **denied.**")

        # Disable buttons after action
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)


async def setup(bot):
    await bot.add_cog(Suggestion(bot))