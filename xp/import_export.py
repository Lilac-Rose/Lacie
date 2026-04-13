import json
import asyncio
from io import BytesIO
import discord
from discord import app_commands
from discord.ext import commands
from xp.utils import xp_for_level
from xp.database import get_db
from moderation.loader import ModerationBase
from .groups import xp_admin_group
from utils.logger import get_logger

logger = get_logger(__name__)


class XPImportExport(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Register both commands onto the shared xpadmin group
        xp_admin_group.add_command(app_commands.command(name="export", description="Export XP data to JSON (lifetime or annual)")(self.export_xp))
        xp_admin_group.add_command(app_commands.command(name="import", description="Import XP data from JSON (overwrites DB)")(self.import_xp))

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
                logger.error(f"Error in _db_work: {e}", exc_info=True)
                raise

        # Run everything in thread pool
        users = await asyncio.to_thread(_db_work)
        return {"users": users}

    @ModerationBase.is_admin()
    @app_commands.choices(
        xp_type=[
            app_commands.Choice(name="Lifetime", value="lifetime"),
            app_commands.Choice(name="Annual", value="annual")
        ]
    )
    async def export_xp(self, interaction: discord.Interaction, xp_type: app_commands.Choice[str]):
        try:
            # Defer immediately
            await interaction.response.defer()
            
            logger.info(f"Export started for {xp_type.value}")

            lifetime = xp_type.value == "lifetime"

            logger.debug("Fetching data from database...")
            data = await self._export_data(lifetime)
            logger.info(f"Data fetched: {len(data['users'])} users")

            json_str = json.dumps(data, indent=2)
            json_bytes = json_str.encode("utf-8")
            logger.debug(f"JSON size: {len(json_bytes)} bytes")

            file = discord.File(fp=BytesIO(json_bytes), filename=f"{xp_type.value}_xp_export.json")

            await interaction.followup.send(
                f"✅ Exported `{xp_type.value}` XP data ({len(data['users'])} users).",
                file=file
            )
            logger.info("Export complete!")

        except Exception as e:
            logger.error(f"Error in export_xp: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"❌ An error occurred during export: {str(e)}")
            except Exception:
                pass

    # ==================== IMPORT ====================

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
                logger.error(f"Error in _db_work: {e}", exc_info=True)
                raise

        # Run database work in thread pool
        count = await asyncio.to_thread(_db_work)
        return count

    @ModerationBase.is_admin()
    @app_commands.choices(
        xp_type=[
            app_commands.Choice(name="Lifetime", value="lifetime"),
            app_commands.Choice(name="Annual", value="annual")
        ]
    )
    async def import_xp(
        self,
        interaction: discord.Interaction,
        xp_type: app_commands.Choice[str],
        attachment: discord.Attachment
    ):
        try:
            # Defer immediately
            await interaction.response.defer()
             
            logger.info(f"Import started for {xp_type.value}")

            lifetime = xp_type.value == "lifetime"

            if not attachment.filename.endswith(".json"):
                await interaction.followup.send("❌ Please upload a valid `.json` file.")
                return

            logger.debug("Downloading attachment...")
            file_bytes = await attachment.read()
            logger.debug(f"Downloaded {len(file_bytes)} bytes")

            try:
                data = json.loads(file_bytes.decode("utf-8"))
            except json.JSONDecodeError as e:
                await interaction.followup.send(f"❌ Invalid JSON file format: {str(e)}")
                return

            users_data = data.get("users", {})

            if not users_data:
                await interaction.followup.send("❌ No user data found in the JSON file.")
                return

            logger.info(f"Found {len(users_data)} users to import")

            count = await self._import_data(users_data, lifetime)
            logger.info(f"Import complete: {count} users")

            await interaction.followup.send(
                f"✅ Imported `{xp_type.value}` XP data from `{attachment.filename}` — {count} users imported (existing data overwritten)."
            )

        except Exception as e:
            logger.error(f"Error in import_xp: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"❌ An error occurred during import: {str(e)}")
            except Exception:
                pass

    async def cog_unload(self):
        xp_admin_group.remove_command("export")
        xp_admin_group.remove_command("import")

async def setup(bot: commands.Bot):
    await bot.add_cog(XPImportExport(bot))