import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import asyncio
import glob

load_dotenv()

TOKEN = os.getenv("TOKEN")
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"))

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

async def load_cogs(folder: str):
    for file in glob.glob(f"{folder}/*.py"):
        if os.path.basename(file) == "__init__.py":
            continue
        module_name = f"{folder}.{os.path.splitext(os.path.basename(file))[0]}"
        try:
            await bot.load_extension(module_name)
            print(f"Loaded {module_name}")
        except Exception as e:
            print(f"Failed to load {module_name}: {e}")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")
    await load_cogs("commands")
    await load_cogs("wordbomb")
    await load_cogs("moderation")

@bot.command(name="reload")
@commands.has_role(ADMIN_ROLE_ID)
async def reload(ctx):
    await load_cogs("commands")
    await load_cogs("moderation")
    await ctx.send("Cogs reloaded successfully!")

async def main():
    async with bot:
        await bot.start(TOKEN)

asyncio.run(main())
