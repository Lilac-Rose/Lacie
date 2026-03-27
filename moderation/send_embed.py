import discord
from discord.ext import commands
from discord.ui import View, Button
import base64
import zlib
import json
from .loader import ModerationBase


class SendEmbedCommand(ModerationBase):
    @commands.command(name="send_embed")
    @ModerationBase.is_admin()
    async def send_embed(self, ctx, channel: discord.TextChannel, *, embed_string: str):
        """
        Send a Discord embed from the embed builder to a specified channel.
        Usage: !send_embed <channel> <embed_string>
        """
        # Decode the embed string
        try:
            async with ctx.typing():
                raw = base64.urlsafe_b64decode(embed_string.encode())
                try:
                    raw = zlib.decompress(raw)
                except zlib.error:
                    pass  # Legacy uncompressed string
                embed_data = json.loads(raw.decode())
                
                # Ensure embed_data is a list (for embed chains)
                if not isinstance(embed_data, list):
                    embed_data = [embed_data]
                
                # Convert embed data to Discord embeds
                embeds = await self._build_embeds(embed_data)
                
                if not embeds:
                    await ctx.send("❌ No valid embeds found in the provided data.")
                    return
                    
        except json.JSONDecodeError as e:
            await ctx.send(f"❌ Invalid embed string. Could not decode JSON: `{e}`")
            return
        except Exception as e:
            await ctx.send(f"❌ Failed to build embeds: `{e}`")
            return
        
        # Confirm before sending
        view = View(timeout=60)
        confirmed = {"value": False}
        
        async def yes_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("You can't confirm this action.", ephemeral=True)
                return
            confirmed["value"] = True
            await interaction.response.edit_message(content="✅ Confirmed. Sending embed...", view=None)
            view.stop()
        
        async def no_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("You can't cancel this action.", ephemeral=True)
                return
            confirmed["value"] = False
            await interaction.response.edit_message(content="❌ Cancelled.", view=None)
            view.stop()
        
        yes_button = Button(label="Yes", style=discord.ButtonStyle.green)
        no_button = Button(label="No", style=discord.ButtonStyle.red)
        yes_button.callback = yes_callback
        no_button.callback = no_callback
        view.add_item(yes_button)
        view.add_item(no_button)
        
        # Send preview
        embed_count = len(embeds)
        preview_text = f"Send {'this embed' if embed_count == 1 else f'{embed_count} embeds'} to {channel.mention}?"
        
        try:
            await ctx.send(
                preview_text,
                embeds=embeds[:10] if len(embeds) <= 10 else embeds[:1],  # Preview max 10 embeds or just first one
                view=view
            )
            
            if len(embeds) > 10:
                await ctx.send(f"⚠️ Preview shows only the first embed. Total embeds to send: {embed_count}")
        except Exception as e:
            await ctx.send(f"❌ Failed to send preview: `{e}`")
            return
        
        await view.wait()
        
        if not confirmed["value"]:
            return
        
        # Send the embeds to the target channel
        try:
            # Discord allows max 10 embeds per message
            for i in range(0, len(embeds), 10):
                chunk = embeds[i:i+10]
                await channel.send(embeds=chunk)
            
            await ctx.send(f"✅ Successfully sent {'embed' if embed_count == 1 else f'{embed_count} embeds'} to {channel.mention}")
            
        except discord.Forbidden:
            await ctx.send(f"❌ I don't have permission to send messages in {channel.mention}")
        except Exception as e:
            await ctx.send(f"❌ Failed to send embeds: `{e}`")
    
    async def _build_embeds(self, embed_data: list) -> list[discord.Embed]:
        """Build Discord embed objects from embed data"""
        embeds = []
        for data in embed_data:
            embed_type = data.get("type", "full")
            
            # Handle image-only embeds
            if embed_type == "image":
                if data.get("image") and data["image"].get("url"):
                    embed = discord.Embed()
                    embed.set_image(url=data["image"]["url"])
                    embeds.append(embed)
                continue
            
            # Handle full embeds
            embed = discord.Embed()
            
            # Basic properties
            if data.get("title"):
                embed.title = data["title"]
            if data.get("description"):
                embed.description = data["description"]
            if data.get("url"):
                embed.url = data["url"]
            if data.get("color"):
                embed.color = data["color"]
            
            # Author
            if data.get("author"):
                author = data["author"]
                embed.set_author(
                    name=author.get("name", ""),
                    url=author.get("url"),
                    icon_url=author.get("icon_url")
                )
            
            # Footer
            if data.get("footer"):
                footer = data["footer"]
                embed.set_footer(
                    text=footer.get("text", ""),
                    icon_url=footer.get("icon_url")
                )
            
            # Timestamp
            if data.get("timestamp"):
                # Discord.py will handle the timestamp if we set it
                from datetime import datetime
                embed.timestamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
            
            # Fields
            if data.get("fields"):
                for field in data["fields"]:
                    if field.get("name") or field.get("value"):
                        embed.add_field(
                            name=field.get("name", "\u200b"),
                            value=field.get("value", "\u200b"),
                            inline=field.get("inline", False)
                        )
            
            # Image
            if data.get("image") and data["image"].get("url"):
                embed.set_image(url=data["image"]["url"])
            
            # Thumbnail
            if data.get("thumbnail") and data["thumbnail"].get("url"):
                embed.set_thumbnail(url=data["thumbnail"]["url"])
            
            embeds.append(embed)
        
        return embeds


async def setup(bot: commands.Bot):
    await bot.add_cog(SendEmbedCommand(bot))