import discord
from discord import app_commands
from discord.ext import commands
from embed.embed_color import get_embed_color

HELP_PAGES = {
    "Fun & Games": [
        ("`/bonk <user>`", "Bonk another user."),
        ("`/coinflip`", "Flip a coin."),
        ("`/diceroll <dice>`", "Roll dice. Supports d4, d6, d8, d10, d12, d20, d100 — e.g. `2d6+3`."),
        ("`/meow`", "Meow."),
        ("`/connect4 <user>`", "Start a game of Connect Four with another user."),
        ("`/tictactoe <user>`", "Start a game of Tic-Tac-Toe with another user."),
        ("`/minesweeper`", "Start a game of Minesweeper. Choose from Easy, Medium, or Hard."),
        ("`/minesweeper_stats`", "View your Minesweeper stats."),
    ],
    "Wordle": [
        ("`/wordle`", "Start today's Wordle game."),
        ("`/wordle_guess <word>`", "Submit a 5-letter guess for today's Wordle."),
        ("`/wordle_stats`", "View your personal Wordle stats."),
        ("`/wordle_serverstats`", "View server-wide Wordle stats."),
    ],
    "XP & Leveling": [
        ("`/xp rank`", "Check your rank or another user's rank. Choose between Lifetime or Annual."),
        ("`/xp top`", "Show the server leaderboard. Filter by Lifetime, Annual, Monthly, Weekly, or Daily XP."),
    ],
    "Sparkles": [
        ("`/sparkle check`", "Check your sparkle count or another user's."),
        ("`/sparkle info`", "Learn about sparkles and how they work."),
        ("`/sparkle leaderboard`", "View the sparkle leaderboard."),
        ("`/sparkle stats`", "View server-wide sparkle statistics."),
    ],
    "Profile": [
        ("`/profile set`", "Set your profile information."),
        ("`/profile view`", "View your profile or another user's."),
        ("`/profile fonts`", "List all available fonts with a visual preview."),
    ],
    "Avatar": [
        ("`/avatar show`", "Show your avatar or another user's."),
        ("`/avatar bitcrush`", "Apply a bitcrush effect to an avatar."),
        ("`/avatar canny_edge`", "Apply Canny edge detection to an avatar."),
        ("`/avatar explode`", "Make an avatar explode."),
        ("`/avatar grayscale`", "Convert an avatar to grayscale."),
        ("`/avatar inverse`", "Invert the colors of an avatar."),
        ("`/avatar kuwahara`", "Apply a Kuwahara filter for a painterly effect."),
        ("`/avatar obamify`", "Turn an avatar into a tile-based Obama mosaic."),
        ("`/avatar bad_apple`", "Play Bad Apple with avatar(s) tiled as the fill."),
    ],
    "Emote Credits": [
        ("`/emote_credit <emote>`", "Find out who created a specific emoji or sticker."),
        ("`/emote_credits_add <emote> <artist>`", "Submit credit information for an emoji or sticker."),
        ("`/emote_credits_update <emote> <artist>`", "Submit a correction to an existing emote credit."),
        ("`/emote_artists`", "List all artists who have credited emotes or stickers."),
        ("`/emote_by_artist <artist>`", "View all emotes and stickers credited to a specific artist."),
    ],
    "Color Roles": [
        ("`/color set <color>`", "Choose your color role."),
        ("`/color remove`", "Remove your current color role."),
        ("`/color list`", "Show all available role colors."),
        ("`/prestige color <prestige>`", "Choose which prestige color to display."),
        ("`/prestige removecolor`", "Remove your prestige color."),
    ],
    "Reminders": [
        ("`/reminder set <duration> <message>`", "Set a reminder using a duration, e.g. `10m`, `2h`, `3d`."),
        ("`/reminder at <time> <message>`", "Set a reminder for a specific date/time, e.g. `April 5 3pm`."),
        ("`/reminder list`", "View all your active reminders."),
        ("`/reminder remove <id>`", "Remove a specific reminder by its ID."),
        ("`/reminder clear`", "Remove all your active reminders."),
    ],
    "Birthdays": [
        ("`/birthday set <date> <timezone>`", "Save your birthday (MM-DD format)."),
        ("`/birthday remove`", "Remove your saved birthday."),
        ("`/birthday list`", "List all birthdays for a specific month."),
    ],
    "Suggestions": [
        ("`/suggest submit <idea>`", "Submit a suggestion for the server or bot."),
        ("`/suggest view <id>`", "View the details of a specific suggestion."),
        ("`/suggest list`", "List all suggestions, with optional status filter."),
        ("`/suggest stats`", "View suggestion stats for yourself or another user."),
    ],
    "Server & Bot": [
        ("`/stats server`", "Show server and bot statistics."),
        ("`/stats messages`", "Show message statistics."),
        ("`/stats words`", "Show word frequency statistics."),
        ("`/ping`", "Check the bot's latency."),
        ("`/infractions`", "View your infractions in this server."),
        ("`/syncroles`", "Manually sync your current roles to the role tracking system."),
        ("`/checkroles`", "Check what roles are saved for you in the database."),
        ("`/faq`", "View frequently asked questions."),
    ],
}


def build_overview_embed(color: discord.Color) -> discord.Embed:
    """Build the top-level overview embed listing all categories and command counts."""
    embed = discord.Embed(
        title="Lacie Help",
        description="Select a category below to see available commands.",
        color=color,
    )
    for category in HELP_PAGES:
        count = len(HELP_PAGES[category])
        embed.add_field(name=category, value=f"{count} command{'s' if count != 1 else ''}", inline=True)
    return embed


def build_category_embed(category: str, color: discord.Color) -> discord.Embed:
    """Build a detail embed listing every command in a category."""
    embed = discord.Embed(title=f"{category}", color=color)
    for command, description in HELP_PAGES[category]:
        embed.add_field(name=command, value=description, inline=False)
    return embed


class HelpSelect(discord.ui.Select):
    """Dropdown that switches between the overview and per-category embeds."""

    def __init__(self, embed_color: discord.Color):
        self.embed_color = embed_color
        options = [discord.SelectOption(label="Overview", value="__overview__")] + [
            discord.SelectOption(label=category, value=category)
            for category in HELP_PAGES
        ]
        super().__init__(placeholder="Select a category...", options=options)

    async def callback(self, interaction: discord.Interaction):
        """Swap the embed for the selected category (or back to overview)."""
        if self.values[0] == "__overview__":
            embed = build_overview_embed(self.embed_color)
        else:
            embed = build_category_embed(self.values[0], self.embed_color)
        await interaction.response.edit_message(embed=embed)


class HelpView(discord.ui.View):
    """View wrapping the HelpSelect dropdown. Times out after 2 minutes of inactivity."""

    def __init__(self, color: discord.Color, owner_id: int):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.add_item(HelpSelect(embed_color=color))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ Only the person who ran this command can use this menu.", ephemeral=True
            )
            return False
        return True


class Help(commands.Cog):
    """Cog providing both the /help slash command and the !help prefix command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="View all available commands")
    async def help_slash(self, interaction: discord.Interaction):
        """Show the interactive help menu via slash command."""
        color = get_embed_color(interaction.user.id)
        embed = build_overview_embed(color)
        await interaction.response.send_message(embed=embed, view=HelpView(color, interaction.user.id))

    @commands.command(name="help")
    async def help_prefix(self, ctx: commands.Context):
        """Show the interactive help menu via prefix command."""
        color = get_embed_color(ctx.author.id)
        embed = build_overview_embed(color)
        await ctx.send(embed=embed, view=HelpView(color, ctx.author.id))


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
