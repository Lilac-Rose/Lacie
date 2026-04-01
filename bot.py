import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import asyncio
import glob
from xp.database import get_db as get_xp_db
from xp.add_xp import add_xp
from moderation.loader import ModerationBase
from sparkle.database import get_db as get_sparkle_db
from xp.groups import xp_group, xp_admin_group
from utils.logger import get_logger, setup_logging

# --- Startup ---
load_dotenv()
setup_logging()

logger = get_logger(__name__)

TOKEN = os.getenv("TOKEN")

# All cog folders to load on startup and reload
COG_FOLDERS = [
    "commands",
    "games",
    "moderation",
    "xp",
    "sparkle",
    "image",
    "suggestion",
    "birthday",
    "embed",
    "profiles",
    "events",
    "stats",
    "wordle",
    "reminders",
    "arg",
]

# --- Bot setup ---
bot = commands.Bot(
    command_prefix="!",
    intents=discord.Intents.all(),
    help_command=None,
    activity=discord.Activity(
        type=discord.ActivityType.playing,
        name="Paper Lily - Chapter 2"
    ))

# Register shared slash command groups defined in xp/groups.py
bot.tree.add_command(xp_group)
bot.tree.add_command(xp_admin_group)

# --- Cog loading ---
async def load_cogs(folder: str):
    non_cog_files = {"add_xp.py", "database.py", "utils.py", "__init__.py", "groups.py", "loader.py", "constants.py"}
    disabled_cogs = {"archipelago_monitor.py"}
    for file in glob.glob(f"{folder}/*.py"):
        filename = os.path.basename(file)
        if filename in non_cog_files:
            logger.debug(f"Skipping {filename} (utility file)")
            continue
        if filename in disabled_cogs:
            module_name = f"{folder}.{os.path.splitext(filename)[0]}"
            if module_name in bot.extensions:
                await bot.unload_extension(module_name)
                logger.info(f"Unloaded disabled cog {module_name}")
            continue
        module_name = f"{folder}.{os.path.splitext(filename)[0]}"
        try:
            if module_name in bot.extensions:
                await bot.reload_extension(module_name)
                logger.info(f"Reloaded {module_name}")
            else:
                await bot.load_extension(module_name)
                logger.info(f"Loaded {module_name}")
        except Exception as e:
            logger.exception(f"Failed to load {module_name}: {e}")

# --- Events and commands ---
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}!")

    for lifetime in (True, False):
        try:
            conn, cur = get_xp_db(lifetime)
            conn.close()
            logger.info(f"XP database connection successful (lifetime={lifetime})")
        except Exception as e:
            logger.error(f"XP database connection failed (lifetime={lifetime}): {e}")

    try:
        conn = get_sparkle_db()
        conn.close()
        logger.info("Sparkle database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize sparkle database: {e}")

    for folder in COG_FOLDERS:
        await load_cogs(folder)

    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash commands")
        for cmd in synced:
            logger.debug(f"  - {cmd.name}")
    except Exception as e:
        logger.exception(f"Failed to sync slash commands: {e}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    logger.error(f"Command error: {error}", exc_info=True)

@bot.command(name="reload")
@ModerationBase.is_admin()
async def reload(ctx):
    """Reload commands cogs and sync slash commands"""
    for folder in COG_FOLDERS:
        await load_cogs(folder)

    try:
        synced = await bot.tree.sync()
        await ctx.send(f"Cogs reloaded successfully! Synced {len(synced)} slash commands.")
    except Exception as e:
        await ctx.send(f"Cogs reloaded but failed to sync slash commands: {e}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    try:
        await add_xp(message.author)
    except Exception as e:
        logger.error(f"XP error: {e}", exc_info=True)
    await bot.process_commands(message)

# --- Entry point ---
async def main():
    try:
        async with bot:
            await bot.start(TOKEN)
    except Exception as e:
        logger.exception(f"Bot startup error: {e}")

if __name__ == "__main__":
    asyncio.run(main())