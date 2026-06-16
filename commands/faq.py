import discord
from discord import app_commands
from discord.ext import commands
from embed.embed_color import get_embed_color

FAQ_ITEMS = [
    (
        "When is Chapter 2 coming out?",
        "We don't know yet, stay tuned!",
    ),
    (
        "How do I not ping someone when I reply to them?",
        "When you click **Reply** on a message, look for the **@On** toggle on the right side of the chat box.\nClick it to switch it to **@Off** and your reply won't ping the user.",
    ),
    (
        "I can't see all the channels — why?",
        "Not all channels are visible by default. You can:\n- Right-click the server icon and select **Show All Channels**\n- Or open **Channels & Roles** at the top of the channel list to pick specific ones",
    ),
    (
        "How do I check my level?",
        "Head to <#876777562599194644> and run `/xp rank`.",
    ),
    (
        "Is this server affiliated with Leef?",
        "No.",
    ),
    (
        "How do I post images / why can't I send embeds?",
        "You need to reach **Level 8** first. Keep chatting to earn XP!\nYou can check how many messages you have left until Level 8 by running `/xp calculate`.",
    ),
    (
        "How do I do something in Paper Lily / Project Kat?",
        "Ask in <#1229700606155821096> or <#1229700691602178098> and someone will help you out!",
    ),
    (
        "How can I contact staff if I have an issue?",
        "DM <@575252669443211264> to open a private thread directly with staff.",
    ),
]


class FAQ(commands.Cog):
    """Cog providing the /faq slash command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="faq", description="View frequently asked questions")
    async def faq(self, interaction: discord.Interaction):
        """Display all FAQ entries in a single embed using the caller's accent colour."""
        embed = discord.Embed(
            title="Frequently Asked Questions",
            color=get_embed_color(interaction.user.id),
        )
        for question, answer in FAQ_ITEMS:
            embed.add_field(name=question, value=answer, inline=False)

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(FAQ(bot))
