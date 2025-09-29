import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import asyncio
import glob
import traceback
from xp.database import get_db as get_xp_db

# Import sparkle DB to ensure it exists
from sparkle.database import get_db as get_sparkle_db

load_dotenv()

TOKEN = os.getenv("TOKEN")
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"))

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

async def load_cogs(folder: str):
    """Load all cogs in the folder except utility files"""
    non_cog_files = {"add_xp.py", "database.py", "utils.py", "__init__.py",
                     "import_old_data.py", "repair_db.py", "reset_db.py"}

    for file in glob.glob(f"{folder}/*.py"):
        filename = os.path.basename(file)
        if filename in non_cog_files:
            print(f"Skipping {filename} (utility file)")
            continue

        module_name = f"{folder}.{os.path.splitext(filename)[0]}"
        try:
            await bot.load_extension(module_name)
            print(f"Loaded {module_name}")
        except Exception as e:
            print(f"Failed to load {module_name}: {e}")
            traceback.print_exc()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")

    # Ensure XP database connection works
    for lifetime in (True, False):
        try:
            conn, cur = get_xp_db(lifetime)
            conn.close()
            print(f"XP database connection successful (lifetime={lifetime})")
        except Exception as e:
            print(f"XP database connection failed (lifetime={lifetime}): {e}")

    # Ensure Sparkle DB exists
    try:
        conn = get_sparkle_db()
        conn.close()
        print("Sparkle database initialized successfully.")
    except Exception as e:
        print(f"Failed to initialize sparkle database: {e}")

    # Load all cogs
    await load_cogs("commands")
    await load_cogs("wordbomb")
    await load_cogs("moderation")
    await load_cogs("xp")
    await load_cogs("sparkle")  # <-- Load sparkle cogs

    # Sync slash commands after loading cogs
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
        for cmd in synced:
            print(f"  - {cmd.name}")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")
        traceback.print_exc()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"Command error: {error}")
    traceback.print_exc()

@bot.command(name="reload")
@commands.has_role(ADMIN_ROLE_ID)
async def reload(ctx):
    """Reload commands cogs and sync slash commands"""
    await load_cogs("commands")
    await load_cogs("moderation")
    await load_cogs("xp")
    await load_cogs("sparkle")  # Reload sparkle cogs

    try:
        synced = await bot.tree.sync()
        await ctx.send(f"Cogs reloaded successfully! Synced {len(synced)} slash commands.")
    except Exception as e:
        await ctx.send(f"Cogs reloaded but failed to sync slash commands: {e}")

# Hook XP into messages
from xp.add_xp import add_xp

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    try:
        await add_xp(message.author)
    except Exception as e:
        print(f"XP error: {e}")
        traceback.print_exc()
    await bot.process_commands(message)

async def main():
    try:
        async with bot:
            await bot.start(TOKEN)
    except Exception as e:
        print(f"Bot startup error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
