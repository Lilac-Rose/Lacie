import json
import asyncio
from io import BytesIO
import discord
from discord import app_commands
from discord.ext import commands
from xp.utils import xp_for_level
from xp.database import get_db
from moderation.loader import ModerationBase

class ImportXP(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _import_data(self, users_data: dict, lifetime: bool):
        """Async function to handle database operations in a thread"""
        def _db_work():
            try:
                conn, cur = get_db(lifetime)
                
                # Drop and recreate the XP table
                cur.execute("DROP TABLE IF EXISTS xp")
                cur.execute("""
                CREATE TABLE xp (
                    user_id TEXT PRIMARY KEY,
                    xp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 0,
                    last_message INTEGER DEFAULT 0
                )
                """)
                
                # Batch insert for much better performance
                insert_data = []
                for user_id, user_info in users_data.items():
                    uid = str(user_id)
                    xp = int(user_info.get("xp", 0))
                    level = 0
                    while xp >= xp_for_level(level + 1):
                        level += 1
                    insert_data.append((uid, xp, level, 0))
                
                # Single executemany call is MUCH faster than individual inserts
                cur.executemany(
                    "INSERT INTO xp (user_id, xp, level, last_message) VALUES (?, ?, ?, ?)",
                    insert_data
                )
                
                conn.commit()
                conn.close()
                return len(insert_data)
            except Exception as e:
                print(f"Error in _db_work: {e}")
                raise
        
        # Run database work in thread pool
        count = await asyncio.to_thread(_db_work)
        return count

    @app_commands.command(name="import_xp", description="Import XP data from JSON (admin only, overwrites DB)")
    @app_commands.choices(
        xp_type=[
            app_commands.Choice(name="Lifetime", value="lifetime"),
            app_commands.Choice(name="Annual", value="annual")
        ]
    )
    @ModerationBase.is_admin()
    async def import_xp(
        self,
        interaction: discord.Interaction,
        xp_type: app_commands.Choice[str],
        attachment: discord.Attachment
    ):
        try:
            # Defer immediately (not ephemeral so everyone can see)
            await interaction.response.defer()
            print(f"Import started for {xp_type.value}")
            
            lifetime = xp_type.value == "lifetime"

            if not attachment.filename.endswith(".json"):
                await interaction.followup.send("❌ Please upload a valid `.json` file.")
                return

            # Download and parse JSON file
            print("Downloading attachment...")
            file_bytes = await attachment.read()
            print(f"Downloaded {len(file_bytes)} bytes")
            
            try:
                print("Parsing JSON...")
                data = json.loads(file_bytes.decode("utf-8"))
            except json.JSONDecodeError as e:
                await interaction.followup.send(f"❌ Invalid JSON file format: {str(e)}")
                return

            users_data = data.get("users", {})
            
            if not users_data:
                await interaction.followup.send("❌ No user data found in the JSON file.")
                return
            
            print(f"Found {len(users_data)} users to import")
            
            # Import data asynchronously
            print("Importing data...")
            count = await self._import_data(users_data, lifetime)
            print(f"Import complete: {count} users")

            await interaction.followup.send(
                f"✅ Imported `{xp_type.value}` XP data from `{attachment.filename}` — {count} users imported (existing data overwritten)."
            )
            
        except Exception as e:
            print(f"Error in import_xp: {e}")
            import traceback
            traceback.print_exc()
            try:
                await interaction.followup.send(f"❌ An error occurred during import: {str(e)}")
            except:
                pass

async def setup(bot: commands.Bot):
    await bot.add_cog(ImportXP(bot))