import discord
from discord import app_commands
from discord.ext import commands
from moderation.loader import ModerationBase
import re
import aiosqlite
from pathlib import Path
from embed.embed_color import get_embed_color

class EmoteCredits(ModerationBase, commands.Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "data" / "emote_credits.db"
        self.approval_channel_id = 1470441786810826884

    async def cog_load(self):
        await self._init_db()

    async def _init_db(self):
        """Initialize the database"""
        async with aiosqlite.connect(self.db_path) as conn:
            # Create credits table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS emote_credits (
                    emote_name TEXT PRIMARY KEY COLLATE NOCASE,
                    artist TEXT NOT NULL,
                    added_by INTEGER,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create pending submissions table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_credits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    emote_name TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    submitted_by INTEGER NOT NULL,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    message_id INTEGER
                )
            """)
            
            await conn.commit()
    
    async def get_credit(self, emote_name: str):
        """Get credit for an emote from database"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT artist FROM emote_credits WHERE LOWER(emote_name) = LOWER(?)",
                (emote_name,)
            ) as cursor:
                result = await cursor.fetchone()
                return result[0] if result else None
    
    async def add_credit(self, emote_name: str, artist: str, added_by: int = None):
        """Add a credit to the database"""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO emote_credits (emote_name, artist, added_by) VALUES (?, ?, ?)",
                (emote_name, artist, added_by)
            )
            await conn.commit()
    
    async def get_all_credits(self):
        """Get all credits from database"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT emote_name FROM emote_credits") as cursor:
                results = {row[0].lower() async for row in cursor}
                return results

    def parse_emoji_name(self, emote_input: str) -> str:
        """Extract emoji name from Discord emoji format or return as-is"""
        emoji_pattern = r'<a?:([^:]+):\d+>'
        match = re.match(emoji_pattern, emote_input)
        if match:
            return match.group(1)
        return emote_input

    @app_commands.command(name="emote_credit", description="Find out who created a specific emoji or sticker")
    @app_commands.describe(emote="The emoji or sticker name (you can type the emoji directly!)")
    async def emote_credit(self, interaction: discord.Interaction, emote: str):
        await interaction.response.defer()
        
        emoji_name = self.parse_emoji_name(emote)
        credit = await self.get_credit(emoji_name)
        
        if credit:
            embed = discord.Embed(
                title=f"🎨 Credit for: {emoji_name}",
                description=f"**Artist:** {credit}",
                color=get_embed_color(interaction.user.id)
            )
            embed.set_footer(text="Full credits document: https://docs.google.com/document/d/1o6dJS3G82rA03oHQn3Lu3ywK0SpepZnxnmP28R8Nnpc/edit?tab=t.0")
            await interaction.followup.send(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Emote Not Found",
                description=f"Sorry, I couldn't find credits for `{emoji_name}`.\n\nMake sure you're using the exact name (e.g., `AoiAlert`, `Lacie Wave`, etc.)\n\nIf you know who made this emote, use `/emote_credits_add` to submit it!",
                color=discord.Color.red()
            )
            embed.set_footer(text="Full credits document: https://docs.google.com/document/d/1o6dJS3G82rA03oHQn3Lu3ywK0SpepZnxnmP28R8Nnpc/edit?tab=t.0")
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="emote_credits_add", description="Submit credit information for an emoji or sticker")
    @app_commands.describe(
        emote="The emoji or sticker (you can type it directly!)",
        artist="The artist's username (e.g., @username)"
    )
    async def emote_credits_add(self, interaction: discord.Interaction, emote: str, artist: str):
        await interaction.response.defer(ephemeral=True)
        
        emoji_name = self.parse_emoji_name(emote)
        
        # Check if credit already exists
        existing_credit = await self.get_credit(emoji_name)
        if existing_credit:
            embed = discord.Embed(
                title="⚠️ Credit Already Exists",
                description=f"**{emoji_name}** already has a credit: {existing_credit}",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Add to pending submissions
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                "INSERT INTO pending_credits (emote_name, artist, submitted_by) VALUES (?, ?, ?)",
                (emoji_name, artist, interaction.user.id)
            )
            submission_id = cursor.lastrowid
            await conn.commit()
        
        approval_channel = self.bot.get_channel(self.approval_channel_id)
        if not approval_channel:
            await interaction.followup.send("❌ Approval channel not found. Please contact an admin.", ephemeral=True)
            return
        
        approval_embed = discord.Embed(
            title="🎨 New Credit Submission",
            color=get_embed_color(interaction.user.id)
        )
        approval_embed.add_field(name="Emote Name", value=f"`{emoji_name}`", inline=False)
        approval_embed.add_field(name="Artist", value=artist, inline=False)
        approval_embed.add_field(name="Submitted By", value=interaction.user.mention, inline=False)
        approval_embed.set_footer(text=f"Submission ID: {submission_id}")
        
        view = CreditApprovalView(self, submission_id, emoji_name, artist, interaction.user.id)
        
        approval_msg = await approval_channel.send(embed=approval_embed, view=view)
        
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "UPDATE pending_credits SET message_id = ? WHERE id = ?",
                (approval_msg.id, submission_id)
            )
            await conn.commit()
        
        # Confirm to user
        embed = discord.Embed(
            title="✅ Submission Sent",
            description=f"Your credit submission for **{emoji_name}** by **{artist}** has been sent for approval!",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="emote_artists", description="List all artists who have credited emotes or stickers")
    async def emote_artists(self, interaction: discord.Interaction):
        await interaction.response.defer()

        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT artist, COUNT(*) as count FROM emote_credits GROUP BY LOWER(artist) ORDER BY count DESC"
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            await interaction.followup.send("No credits in the database yet.", ephemeral=True)
            return

        lines = [f"**{artist}** — {count} emote{'s' if count != 1 else ''}" for artist, count in rows]
        chunks = [lines[i:i+20] for i in range(0, len(lines), 20)]

        embeds = []
        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title=f"🎨 Emote Artists (Page {i+1}/{len(chunks)})",
                description="\n".join(chunk),
                color=get_embed_color(interaction.user.id)
            )
            embed.set_footer(text=f"Total artists: {len(rows)} • Use /emote_by_artist to see an artist's work")
            embeds.append(embed)

        await interaction.followup.send(embed=embeds[0])
        for embed in embeds[1:]:
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="emote_by_artist", description="View all emotes and stickers credited to a specific artist")
    @app_commands.describe(artist="The artist's name to look up")
    async def emote_by_artist(self, interaction: discord.Interaction, artist: str):
        await interaction.response.defer()

        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT emote_name FROM emote_credits WHERE LOWER(artist) = LOWER(?) ORDER BY emote_name",
                (artist,)
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            # Try a partial match and suggest
            async with aiosqlite.connect(self.db_path) as conn:
                async with conn.execute(
                    "SELECT DISTINCT artist FROM emote_credits WHERE LOWER(artist) LIKE LOWER(?) ORDER BY artist",
                    (f"%{artist}%",)
                ) as cursor:
                    suggestions = [r[0] for r in await cursor.fetchall()]

            if suggestions:
                await interaction.followup.send(
                    f"No artist named **{artist}** found. Did you mean: {', '.join(f'`{s}`' for s in suggestions[:5])}?",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(f"No artist named **{artist}** found.", ephemeral=True)
            return

        emote_names = [r[0] for r in rows]
        guild_emoji_map = {e.name.lower(): e for e in interaction.guild.emojis}

        lines = []
        for name in emote_names:
            emoji = guild_emoji_map.get(name.lower())
            lines.append(f"{emoji} `{name}`" if emoji else f"`{name}`")

        chunks = [lines[i:i+20] for i in range(0, len(lines), 20)]
        embeds = []
        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title=f"🎨 Emotes by {artist} (Page {i+1}/{len(chunks)})",
                description="\n".join(chunk),
                color=get_embed_color(interaction.user.id)
            )
            embed.set_footer(text=f"Total: {len(emote_names)} emote{'s' if len(emote_names) != 1 else ''}")
            embeds.append(embed)

        await interaction.followup.send(embed=embeds[0])
        for embed in embeds[1:]:
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="missing_credits", description="[Admin] List all server emotes and stickers without credits")
    @ModerationBase.is_admin()
    async def missing_credits(self, interaction: discord.Interaction):
        """List all server emotes and stickers that don't have credits"""
        await interaction.response.defer()
        
        missing_emojis = []
        missing_stickers = []
        
        credited_emotes = await self.get_all_credits()
        
        # Check server emojis
        for emoji in interaction.guild.emojis:
            if emoji.name.lower() not in credited_emotes:
                missing_emojis.append(emoji)
        
        # Check server stickers
        for sticker in interaction.guild.stickers:
            if sticker.name.lower() not in credited_emotes:
                missing_stickers.append(sticker)
        
        # Build response
        if not missing_emojis and not missing_stickers:
            embed = discord.Embed(
                title="✅ All Emotes Have Credits!",
                description="Every emoji and sticker in this server has proper credits.",
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed)
            return
        
        # Create embeds for missing items
        embeds = []
        
        if missing_emojis:
            emoji_chunks = [missing_emojis[i:i+20] for i in range(0, len(missing_emojis), 20)]
            for i, chunk in enumerate(emoji_chunks):
                emoji_list = "\n".join([f"• {emoji} - `{emoji.name}`" for emoji in chunk])
                embed = discord.Embed(
                    title=f"⚠️ Emojis Missing Credits ({i+1}/{len(emoji_chunks)})",
                    description=emoji_list,
                    color=discord.Color.orange()
                )
                embed.set_footer(text=f"Total missing emojis: {len(missing_emojis)}")
                embeds.append(embed)
        
        if missing_stickers:
            sticker_chunks = [missing_stickers[i:i+20] for i in range(0, len(missing_stickers), 20)]
            for i, chunk in enumerate(sticker_chunks):
                sticker_list = "\n".join([f"• `{sticker.name}`" for sticker in chunk])
                embed = discord.Embed(
                    title=f"⚠️ Stickers Missing Credits ({i+1}/{len(sticker_chunks)})",
                    description=sticker_list,
                    color=discord.Color.orange()
                )
                embed.set_footer(text=f"Total missing stickers: {len(missing_stickers)}")
                embeds.append(embed)
        
        # Send first embed as response
        if embeds:
            await interaction.followup.send(embed=embeds[0])
            
            # Send remaining embeds as followup messages
            for embed in embeds[1:]:
                await interaction.followup.send(embed=embed)
        
        # Send summary
        summary = f"**Summary:**\n"
        summary += f"Missing emojis: {len(missing_emojis)}\n"
        summary += f"Missing stickers: {len(missing_stickers)}\n"
        summary += f"Total missing: {len(missing_emojis) + len(missing_stickers)}"
        await interaction.followup.send(summary)

    @commands.command(name="missing_credits")
    @ModerationBase.is_admin()
    async def missing_credits_text(self, ctx):
        """List all server emotes and stickers that don't have credits"""
        missing_emojis = []
        missing_stickers = []
        
        credited_emotes = await self.get_all_credits()
        
        # Check server emojis
        for emoji in ctx.guild.emojis:
            if emoji.name.lower() not in credited_emotes:
                missing_emojis.append(emoji)
        
        # Check server stickers
        for sticker in ctx.guild.stickers:
            if sticker.name.lower() not in credited_emotes:
                missing_stickers.append(sticker)
        
        # Build response
        if not missing_emojis and not missing_stickers:
            embed = discord.Embed(
                title="✅ All Emotes Have Credits!",
                description="Every emoji and sticker in this server has proper credits.",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
            return
        
        # Create embeds for missing items
        embeds = []
        
        if missing_emojis:
            emoji_chunks = [missing_emojis[i:i+20] for i in range(0, len(missing_emojis), 20)]
            for i, chunk in enumerate(emoji_chunks):
                emoji_list = "\n".join([f"• {emoji} - `{emoji.name}`" for emoji in chunk])
                embed = discord.Embed(
                    title=f"⚠️ Emojis Missing Credits ({i+1}/{len(emoji_chunks)})",
                    description=emoji_list,
                    color=discord.Color.orange()
                )
                embed.set_footer(text=f"Total missing emojis: {len(missing_emojis)}")
                embeds.append(embed)
        
        if missing_stickers:
            sticker_chunks = [missing_stickers[i:i+20] for i in range(0, len(missing_stickers), 20)]
            for i, chunk in enumerate(sticker_chunks):
                sticker_list = "\n".join([f"• `{sticker.name}`" for sticker in chunk])
                embed = discord.Embed(
                    title=f"⚠️ Stickers Missing Credits ({i+1}/{len(sticker_chunks)})",
                    description=sticker_list,
                    color=discord.Color.orange()
                )
                embed.set_footer(text=f"Total missing stickers: {len(missing_stickers)}")
                embeds.append(embed)
        
        # Send all embeds
        for embed in embeds:
            await ctx.send(embed=embed)
        
        # Send summary
        summary = f"**Summary:**\n"
        summary += f"Missing emojis: {len(missing_emojis)}\n"
        summary += f"Missing stickers: {len(missing_stickers)}\n"
        summary += f"Total missing: {len(missing_emojis) + len(missing_stickers)}"
        await ctx.send(summary)


class CreditApprovalView(discord.ui.View):
    def __init__(self, cog, submission_id, emote_name, artist, submitted_by):
        super().__init__(timeout=None)
        self.cog = cog
        self.submission_id = submission_id
        self.emote_name = emote_name
        self.artist = artist
        self.submitted_by = submitted_by
    
    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id="approve_credit")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Add to database
        await self.cog.add_credit(self.emote_name, self.artist, interaction.user.id)
        
        # Remove from pending
        async with aiosqlite.connect(self.cog.db_path) as conn:
            await conn.execute("DELETE FROM pending_credits WHERE id = ?", (self.submission_id,))
            await conn.commit()
        
        # Update message
        embed = discord.Embed(
            title="✅ Credit Approved",
            color=discord.Color.green()
        )
        embed.add_field(name="Emote Name", value=f"`{self.emote_name}`", inline=False)
        embed.add_field(name="Artist", value=self.artist, inline=False)
        embed.add_field(name="Approved By", value=interaction.user.mention, inline=False)
        
        await interaction.response.edit_message(embed=embed, view=None)
        
        # Notify submitter
        try:
            submitter = await self.cog.bot.fetch_user(self.submitted_by)
            notify_embed = discord.Embed(
                title="✅ Your Credit Submission Was Approved!",
                description=f"**{self.emote_name}** by **{self.artist}** has been added to the credits database.",
                color=discord.Color.green()
            )
            await submitter.send(embed=notify_embed)
        except Exception:
            pass
    
    @discord.ui.button(label="Deny", style=discord.ButtonStyle.red, custom_id="deny_credit")
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Remove from pending
        async with aiosqlite.connect(self.cog.db_path) as conn:
            await conn.execute("DELETE FROM pending_credits WHERE id = ?", (self.submission_id,))
            await conn.commit()
        
        # Update message
        embed = discord.Embed(
            title="❌ Credit Denied",
            color=discord.Color.red()
        )
        embed.add_field(name="Emote Name", value=f"`{self.emote_name}`", inline=False)
        embed.add_field(name="Artist", value=self.artist, inline=False)
        embed.add_field(name="Denied By", value=interaction.user.mention, inline=False)
        
        await interaction.response.edit_message(embed=embed, view=None)
        
        # Notify submitter
        try:
            submitter = await self.cog.bot.fetch_user(self.submitted_by)
            notify_embed = discord.Embed(
                title="❌ Your Credit Submission Was Denied",
                description=f"Your submission for **{self.emote_name}** by **{self.artist}** was not approved.",
                color=discord.Color.red()
            )
            await submitter.send(embed=notify_embed)
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(EmoteCredits(bot))