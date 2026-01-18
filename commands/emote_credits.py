import discord
from discord import app_commands
from discord.ext import commands
from moderation.loader import ModerationBase
import re

class EmoteCredits(ModerationBase, commands.Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        
        # Credit data structure
        self.emoji_credits = {
            # Stickers
            "Aoi Boom": "@bluexmagic",
            "Lacie You Can Cook": "@bluexmagic",
            "Hiro Party": "@bluexmagic",
            "Alba Smug": "@bluexmagic",
            "Got more runes?": "@bluexmagic",
            "Moths Pointing": "@bluexmagic",
            "Nah, Lacie'd Win": "@bluexmagic",
            "Alba Pout": "@frostyj.",
            "Alba Angry": "@frostyj.",
            "Katgirl Question": "@frostyj.",
            "Lacie Shrug": "@frostyj.",
            "Milion Giggle": "@frostyj.",
            "Shadow Girl Surprised": "@frostyj.",
            "Lacie Thumbs Up": "@geniymk",
            "Lacie Stare": "@geniymk",
            "Aoi Sadge": "@geniymk",
            "Alba Bonk": "@geniymk",
            "Lacie Cut It Off": "@geniymk",
            "Catgirl Lacie Peek": "@nekoingeneral",
            "Lacie Sai Hug": "@nekoingeneral",
            "Lacie Bwaa": "@nekoingeneral",
            "It's Albover": "@taplii",
            "Lilith Sip": "@taplii",
            "Milion Sip": "@taplii",
            "Aoi Sorry": "@abdi5930",
            "Alba Hug Fish": "@elurill",
            "Shadow Girl Dance": "@enashinonomeyuri",
            "Catgirl Lacie Surprised": "@ianghuofengmeng",
            "Lacie Heart": "@light_inthedarkness",
            "Kett Depressed": "@rinn_x23",
            "Lacie Wave": "@STATICLOVER_ on Twitter",
            "Lacie Breaking Chains": "@toa_stardust",
            
            # Emojis
            "AoiAlert": "@auatin_archon",
            "LacieSilly": "@auatin_archon",
            "SaiSilly": "@auatin_archon",
            "AoiSilly": "@auatin_archon",
            "RuneSilly": "@auatin_archon",
            "AlbaSilly": "@auatin_archon",
            "ShadowGirlSilly": "@auatin_archon",
            "MilionSilly": "@auatin_archon",
            "AoiSalute": "@_finitus",
            "AoiSkrunkly": "@_finitus",
            "KatTroll": "@taplii",
            "LacieSip": "@taplii",
            "LacieTroll": "@bluexmagic",
            "LacieDoro": "@faketier",
            "AoiGun": "@frostyj.",
            "KatClueless": "@its.tempo",
            "RuneHug": "@rinn_x23",
            "LacieFumo": "@schaferine",
            "HiroFumo": "@spiresto",
            "KatSilly": "@starduststrawby",
            "LacieAutismCreature": "@toa_stardust",
        }

    def parse_emoji_name(self, emote_input: str) -> str:
        """Extract emoji name from Discord emoji format or return as-is"""
        # Match Discord emoji format: <:name:id> or <a:name:id> for animated
        emoji_pattern = r'<a?:([^:]+):\d+>'
        match = re.match(emoji_pattern, emote_input)
        if match:
            return match.group(1)
        return emote_input

    @app_commands.command(name="emote_credit", description="Find out who created a specific emoji or sticker")
    @app_commands.describe(emote="The emoji or sticker name (you can type the emoji directly!)")
    async def emote_credit(self, interaction: discord.Interaction, emote: str):
        # Defer the response to prevent timeout
        await interaction.response.defer()
        
        # Parse the emoji name from Discord format
        emoji_name = self.parse_emoji_name(emote)
        
        # Try to find the credit (case-insensitive search)
        credit = None
        matched_name = None
        
        # First try exact match
        if emoji_name in self.emoji_credits:
            credit = self.emoji_credits[emoji_name]
            matched_name = emoji_name
        else:
            # Try case-insensitive match
            for key in self.emoji_credits:
                if key.lower() == emoji_name.lower():
                    credit = self.emoji_credits[key]
                    matched_name = key
                    break
        
        if credit:
            embed = discord.Embed(
                title=f"🎨 Credit for: {matched_name}",
                description=f"**Artist:** {credit}",
                color=discord.Color.blue()
            )
            embed.set_footer(text="Full credits document: https://docs.google.com/document/d/1o6dJS3G82rA03oHQn3Lu3ywK0SpepZnxnmP28R8Nnpc/edit?tab=t.0")
            await interaction.followup.send(embed=embed)
        else:
            # Create a helpful error message
            embed = discord.Embed(
                title="❌ Emote Not Found",
                description=f"Sorry, I couldn't find credits for `{emoji_name}`.\n\nMake sure you're using the exact name (e.g., `AoiAlert`, `Lacie Wave`, etc.). But there's a good chance we just haven't added credits for it yet. If you notice an emote that doesnt have credits and know who made it, please DM <@252130669919076352>",
                color=discord.Color.red()
            )
            embed.set_footer(text="Full credits document: https://docs.google.com/document/d/1o6dJS3G82rA03oHQn3Lu3ywK0SpepZnxnmP28R8Nnpc/edit?tab=t.0")
            await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.command(name="missing_credits")
    @ModerationBase.is_admin()
    async def missing_credits(self, ctx):
        """List all server emotes and stickers that don't have credits"""
        await ctx.send("🔍 Checking for emotes and stickers without credits...")
        
        missing_emojis = []
        missing_stickers = []
        
        # Check server emojis
        for emoji in ctx.guild.emojis:
            # Case-insensitive check
            has_credit = any(key.lower() == emoji.name.lower() for key in self.emoji_credits.keys())
            if not has_credit:
                missing_emojis.append(emoji)
        
        # Check server stickers
        for sticker in ctx.guild.stickers:
            # Case-insensitive check
            has_credit = any(key.lower() == sticker.name.lower() for key in self.emoji_credits.keys())
            if not has_credit:
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

async def setup(bot):
    await bot.add_cog(EmoteCredits(bot))