import os
import json
import asyncio
from io import BytesIO
import discord
from discord import app_commands
from discord.ext import commands
from xp.database import get_db

class ExportXP(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _export_data(self, lifetime: bool):
        """Async function to handle database operations in a thread"""
        def _db_work():
            try:
                conn, cur = get_db(lifetime)
                # Fetch all data at once as a list of dicts for faster processing
                cur.execute("SELECT user_id, xp, level, last_message FROM xp")
                rows = cur.fetchall()
                conn.close()
                
                # Build dict directly in the thread
                users = {}
                for user_id, xp, level, last_msg in rows:
                    users[str(user_id)] = {
                        "xp": xp,
                        "level": level,
                        "last_message": last_msg
                    }
                return users
            except Exception as e:
                print(f"Error in _db_work: {e}")
                raise
        
        # Run everything in thread pool
        users = await asyncio.to_thread(_db_work)
        return {"users": users}

    @app_commands.command(name="export_xp", description="Export XP data to JSON (lifetime or annual)")
    @app_commands.choices(
        xp_type=[
            app_commands.Choice(name="Lifetime", value="lifetime"),
            app_commands.Choice(name="Annual", value="annual")
        ]
    )
    async def export_xp(self, interaction: discord.Interaction, xp_type: app_commands.Choice[str]):
        try:
            # Defer immediately (not ephemeral so everyone can see)
            await interaction.response.defer()
            print(f"Export started for {xp_type.value}")
            
            lifetime = xp_type.value == "lifetime"
            
            # Get data asynchronously
            print("Fetching data from database...")
            data = await self._export_data(lifetime)
            print(f"Data fetched: {len(data['users'])} users")
            
            # Create file with pretty-printed JSON
            print("Encoding JSON...")
            json_str = json.dumps(data, indent=2)
            json_bytes = json_str.encode("utf-8")
            print(f"JSON size: {len(json_bytes)} bytes")
            
            print("Creating Discord file...")
            file = discord.File(fp=BytesIO(json_bytes), filename=f"{xp_type.value}_xp_export.json")
            
            # Public response
            print("Sending response...")
            await interaction.followup.send(
                f"✅ Exported `{xp_type.value}` XP data ({len(data['users'])} users).",
                file=file
            )
            print("Export complete!")
            
        except Exception as e:
            print(f"Error in export_xp: {e}")
            import traceback
            traceback.print_exc()
            try:
                await interaction.followup.send(f"❌ An error occurred during export: {str(e)}")
            except:
                pass

async def setup(bot: commands.Bot):
    await bot.add_cog(ExportXP(bot))