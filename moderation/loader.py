import discord
from discord.ext import commands, tasks
import os
import sqlite3
import asyncio
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"))

class ModerationBase(commands.Cog):
    """Base cog for moderation commands with shared DB and utilities"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = os.path.join(os.path.dirname(__file__), "moderation.db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.c = self.conn.cursor()
        self.initialize_db()
        self.check_mutes.start()
        print(f"✅ ModerationBase initialized. DB path: {self.db_path}")

    def cog_unload(self):
        """Ensure database connection closes when the cog unloads."""
        self.check_mutes.cancel()
        self.conn.close()

    def initialize_db(self):
        # Infractions table
        self.c.execute("""
        CREATE TABLE IF NOT EXISTS infractions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            reason TEXT,
            moderator_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL
        )
        """)
        # Mutes table
        self.c.execute("""
        CREATE TABLE IF NOT EXISTS mutes (
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            unmute_time TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, guild_id)
        )
        """)
        self.conn.commit()

    @staticmethod
    def is_admin():
        """Decorator that checks if the command author has the admin role."""
        async def predicate(ctx: commands.Context):
            if not any(role.id == ADMIN_ROLE_ID for role in ctx.author.roles):
                await ctx.send("You do not have permission to use this command.")
                return False
            return True
        return commands.check(predicate)

    async def log_infraction(self, guild_id: int, user_id: int, mod_id: int, type_: str, reason: str | None):
        """Log an infraction to the database."""
        self.c.execute("""
            INSERT INTO infractions (user_id, guild_id, type, reason, moderator_id, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, guild_id, type_, reason, mod_id, datetime.utcnow().isoformat()))
        self.conn.commit()

    @tasks.loop(seconds=30)
    async def check_mutes(self):
        """Periodically check for expired mutes."""
        if not self.bot.is_ready():
            print("⏳ Bot not ready yet, skipping mute check")
            return
            
        now = datetime.utcnow()
        
        print(f"\n🔍 Checking mutes at {now.isoformat()}")
        print(f"   Bot is in {len(self.bot.guilds)} guild(s)")
        
        self.c.execute("SELECT * FROM mutes")
        mutes = self.c.fetchall()

        if not mutes:
            print("   No active mutes in database")
            return

        print(f"   Found {len(mutes)} active mute(s)")

        for mute in mutes:
            print(f"\n   Checking mute for user {mute['user_id']} in guild {mute['guild_id']}")
            
            try:
                unmute_time = datetime.fromisoformat(mute["unmute_time"])
                print(f"   Unmute time: {unmute_time.isoformat()}")
                print(f"   Current time: {now.isoformat()}")
                print(f"   Should unmute: {now >= unmute_time}")
            except ValueError as e:
                print(f"   ❌ Error parsing unmute time: {e}")
                continue

            if now >= unmute_time:
                print(f"   ⏰ Time to unmute user {mute['user_id']}")
                
                # List all guilds bot can see
                print(f"   Bot can see guilds: {[g.id for g in self.bot.guilds]}")
                
                guild = self.bot.get_guild(mute["guild_id"])
                if not guild:
                    print(f"   ❌ Guild {mute['guild_id']} not found in bot's guild cache")
                    print(f"   This likely means the bot left the server or has incorrect intents")
                    # Remove stale mute
                    self.c.execute("DELETE FROM mutes WHERE user_id = ? AND guild_id = ?", 
                                  (mute["user_id"], mute["guild_id"]))
                    self.conn.commit()
                    continue
                
                print(f"   ✅ Found guild: {guild.name}")

                # Fetch member, even if offline
                try:
                    member = guild.get_member(mute["user_id"])
                    if not member:
                        print(f"   Member not in cache, fetching...")
                        member = await guild.fetch_member(mute["user_id"])
                        print(f"   ✅ Fetched member {member}")
                    else:
                        print(f"   ✅ Found member {member}")
                except discord.NotFound:
                    print(f"   ❌ Member {mute['user_id']} not found in guild (may have left)")
                    # Remove from DB since user left
                    self.c.execute("DELETE FROM mutes WHERE user_id = ? AND guild_id = ?", 
                                  (mute["user_id"], mute["guild_id"]))
                    self.conn.commit()
                    continue
                except Exception as e:
                    print(f"   ❌ Error fetching member: {e}")
                    continue

                mute_role = guild.get_role(982702037517090836)
                if not mute_role:
                    print(f"   ❌ Mute role (982702037517090836) not found in guild")
                    continue

                print(f"   ✅ Found mute role: {mute_role.name}")
                print(f"   Member has mute role: {mute_role in member.roles}")
                print(f"   Member's roles: {[r.name for r in member.roles]}")

                if mute_role in member.roles:
                    print(f"   Attempting to remove mute role...")
                    try:
                        await member.remove_roles(mute_role, reason="Mute duration expired")
                        print(f"   ✅ Successfully removed mute role")
                        
                        await self.log_infraction(
                            guild.id, member.id, self.bot.user.id,
                            "unmute", "Automatic unmute (duration expired)"
                        )
                        print(f"   ✅ Logged infraction")

                        # Send message in the original channel
                        channel = guild.get_channel(mute["channel_id"])
                        if channel:
                            try:
                                await channel.send(f"{member.mention} has been automatically unmuted (duration expired).")
                                print(f"   ✅ Sent unmute message in #{channel.name}")
                            except Exception as e:
                                print(f"   ⚠️ Error sending message: {e}")
                        else:
                            print(f"   ⚠️ Channel {mute['channel_id']} not found")

                    except discord.Forbidden:
                        print(f"   ❌ Permission denied - bot cannot remove roles")
                    except Exception as e:
                        print(f"   ❌ Error unmuting {member}: {type(e).__name__}: {e}")
                        # Don't remove from DB if unmute failed
                        continue
                else:
                    print(f"   ⚠️ User doesn't have mute role (maybe already manually unmuted?)")

                # Remove from DB only if we got this far
                print(f"   Removing from database...")
                self.c.execute("DELETE FROM mutes WHERE user_id = ? AND guild_id = ?", 
                              (mute["user_id"], mute["guild_id"]))
                self.conn.commit()
                print(f"   ✅ Removed mute record from database")
            else:
                time_left = unmute_time - now
                print(f"   ⏳ Mute still active. Time remaining: {time_left}")

    @check_mutes.before_loop
    async def before_check_mutes(self):
        await self.bot.wait_until_ready()
        # Wait an extra 5 seconds for guild cache to fully populate
        await asyncio.sleep(5)
        print("✅ check_mutes task started (after cache warmup)")

async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationBase(bot))