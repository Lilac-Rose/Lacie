import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
from datetime import datetime, timezone, timedelta
import asyncio
import pytz
import os
from dotenv import load_dotenv
from moderation.loader import ModerationBase

load_dotenv()
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"), 0)
BIRTHDAY_ROLE_ID = 1113751318918602762

class Birthday(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = os.path.join(os.path.dirname(__file__), "birthdays.db")
        self._init_db()
        self.check_birthdays.start()
        self.remove_birthday_roles.start()
    
    def cog_unload(self):
        self.check_birthdays.cancel()
        self.remove_birthday_roles.cancel()

    def _init_db(self):
        """Initialize SQLite database."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
                  CREATE TABLE IF NOT EXISTS birthdays (
                  user_id INTEGER PRIMARY KEY,
                  birthday TEXT NOT NULL,
                  timezone TEXT NOT NULL
                  )
            """)
        c.execute("""
                  CREATE TABLE IF NOT EXISTS guild_settings (
                  guild_id INTEGER PRIMARY KEY,
                  channel_id INTEGER
                  )
            """)
        c.execute("""
                  CREATE TABLE IF NOT EXISTS active_birthday_roles (
                  user_id INTEGER,
                  guild_id INTEGER,
                  granted_at TEXT NOT NULL,
                  PRIMARY KEY (user_id, guild_id)
                  )
            """)
        conn.commit()
        conn.close()

    async def timezone_autocomplete(self, interaction: discord.Interaction, current: str):
        all_timezones = [
            ("UTC", "UTC"),
            # North America
            ("US Eastern (America/New_York)", "America/New_York"),
            ("US Central (America/Chicago)", "America/Chicago"),
            ("US Mountain (America/Denver)", "America/Denver"),
            ("US Pacific (America/Los_Angeles)", "America/Los_Angeles"),
            ("Alaska (America/Anchorage)", "America/Anchorage"),
            ("Hawaii (Pacific/Honolulu)", "Pacific/Honolulu"),
            ("Canada Atlantic (America/Halifax)", "America/Halifax"),
            ("Canada Central (America/Winnipeg)", "America/Winnipeg"),
            ("Canada Mountain (America/Edmonton)", "America/Edmonton"),
            ("Canada Pacific (America/Vancouver)", "America/Vancouver"),
            ("Canada Eastern (America/Toronto)", "America/Toronto"),
            ("Newfoundland (America/St_Johns)", "America/St_Johns"),
            ("Mexico City (America/Mexico_City)", "America/Mexico_City"),
            # South America
            ("Brazil (America/Sao_Paulo)", "America/Sao_Paulo"),
            ("Argentina (America/Argentina/Buenos_Aires)", "America/Argentina/Buenos_Aires"),
            ("Chile (America/Santiago)", "America/Santiago"),
            ("Colombia (America/Bogota)", "America/Bogota"),
            ("Peru (America/Lima)", "America/Lima"),
            ("Venezuela (America/Caracas)", "America/Caracas"),
            # Europe
            ("UK (Europe/London)", "Europe/London"),
            ("Ireland (Europe/Dublin)", "Europe/Dublin"),
            ("Portugal (Europe/Lisbon)", "Europe/Lisbon"),
            ("Spain (Europe/Madrid)", "Europe/Madrid"),
            ("France (Europe/Paris)", "Europe/Paris"),
            ("Netherlands (Europe/Amsterdam)", "Europe/Amsterdam"),
            ("Belgium (Europe/Brussels)", "Europe/Brussels"),
            ("Germany (Europe/Berlin)", "Europe/Berlin"),
            ("Switzerland (Europe/Zurich)", "Europe/Zurich"),
            ("Italy (Europe/Rome)", "Europe/Rome"),
            ("Austria (Europe/Vienna)", "Europe/Vienna"),
            ("Poland (Europe/Warsaw)", "Europe/Warsaw"),
            ("Czech Republic (Europe/Prague)", "Europe/Prague"),
            ("Greece (Europe/Athens)", "Europe/Athens"),
            ("Turkey (Europe/Istanbul)", "Europe/Istanbul"),
            ("Romania (Europe/Bucharest)", "Europe/Bucharest"),
            ("Sweden (Europe/Stockholm)", "Europe/Stockholm"),
            ("Norway (Europe/Oslo)", "Europe/Oslo"),
            ("Denmark (Europe/Copenhagen)", "Europe/Copenhagen"),
            ("Finland (Europe/Helsinki)", "Europe/Helsinki"),
            ("Russia Moscow (Europe/Moscow)", "Europe/Moscow"),
            ("Russia Yekaterinburg (Asia/Yekaterinburg)", "Asia/Yekaterinburg"),
            ("Russia Novosibirsk (Asia/Novosibirsk)", "Asia/Novosibirsk"),
            ("Russia Vladivostok (Asia/Vladivostok)", "Asia/Vladivostok"),
            # Middle East & Central Asia
            ("UAE/Dubai (Asia/Dubai)", "Asia/Dubai"),
            ("Saudi Arabia (Asia/Riyadh)", "Asia/Riyadh"),
            ("Israel (Asia/Jerusalem)", "Asia/Jerusalem"),
            ("Iran (Asia/Tehran)", "Asia/Tehran"),
            ("Pakistan (Asia/Karachi)", "Asia/Karachi"),
            ("Afghanistan (Asia/Kabul)", "Asia/Kabul"),
            ("Kazakhstan (Asia/Almaty)", "Asia/Almaty"),
            # South Asia
            ("India (Asia/Kolkata)", "Asia/Kolkata"),
            ("Sri Lanka (Asia/Colombo)", "Asia/Colombo"),
            ("Bangladesh (Asia/Dhaka)", "Asia/Dhaka"),
            ("Nepal (Asia/Kathmandu)", "Asia/Kathmandu"),
            # Southeast Asia
            ("Thailand (Asia/Bangkok)", "Asia/Bangkok"),
            ("Vietnam (Asia/Ho_Chi_Minh)", "Asia/Ho_Chi_Minh"),
            ("Myanmar (Asia/Yangon)", "Asia/Yangon"),
            ("Malaysia (Asia/Kuala_Lumpur)", "Asia/Kuala_Lumpur"),
            ("Singapore (Asia/Singapore)", "Asia/Singapore"),
            ("Indonesia West (Asia/Jakarta)", "Asia/Jakarta"),
            ("Indonesia Central (Asia/Makassar)", "Asia/Makassar"),
            ("Indonesia East (Asia/Jayapura)", "Asia/Jayapura"),
            ("Philippines (Asia/Manila)", "Asia/Manila"),
            # East Asia
            ("China (Asia/Shanghai)", "Asia/Shanghai"),
            ("Hong Kong (Asia/Hong_Kong)", "Asia/Hong_Kong"),
            ("Taiwan (Asia/Taipei)", "Asia/Taipei"),
            ("Japan (Asia/Tokyo)", "Asia/Tokyo"),
            ("Korea (Asia/Seoul)", "Asia/Seoul"),
            ("Mongolia (Asia/Ulaanbaatar)", "Asia/Ulaanbaatar"),
            # Oceania
            ("Australia Western (Australia/Perth)", "Australia/Perth"),
            ("Australia Central (Australia/Adelaide)", "Australia/Adelaide"),
            ("Australia Eastern (Australia/Sydney)", "Australia/Sydney"),
            ("Australia Queensland (Australia/Brisbane)", "Australia/Brisbane"),
            ("New Zealand (Pacific/Auckland)", "Pacific/Auckland"),
            ("Fiji (Pacific/Fiji)", "Pacific/Fiji"),
            ("Papua New Guinea (Pacific/Port_Moresby)", "Pacific/Port_Moresby"),
            # Africa
            ("South Africa (Africa/Johannesburg)", "Africa/Johannesburg"),
            ("Egypt (Africa/Cairo)", "Africa/Cairo"),
            ("Nigeria (Africa/Lagos)", "Africa/Lagos"),
            ("Kenya (Africa/Nairobi)", "Africa/Nairobi"),
            ("Morocco (Africa/Casablanca)", "Africa/Casablanca"),
            ("Ethiopia (Africa/Addis_Ababa)", "Africa/Addis_Ababa"),
        ]
        
        # Filter timezones based on what user is typing
        filtered = [
            app_commands.Choice(name=name, value=value)
            for name, value in all_timezones
            if current.lower() in name.lower()
        ]
        
        return filtered[:25]  # Discord limit of 25 at a time

    # Create command groups
    birthday_group = app_commands.Group(name="birthday", description="Manage birthday settings")
    
    @birthday_group.command(name="set", description="Set your birthday and timezone")
    @app_commands.describe(date="Your birthday (MM-DD)", timezone="Your timezone, search your city/country to find it!")
    @app_commands.autocomplete(timezone=timezone_autocomplete)
    async def set_birthday(self, interaction: discord.Interaction, date: str, timezone: str):
        try:
            datetime.strptime(date, "%m-%d")
        except ValueError:
            await interaction.response.send_message("Invalid date format! Use MM-DD.", ephemeral=True)
            return
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
                    INSERT INTO birthdays (user_id, birthday, timezone)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET birthday=excluded.birthday, timezone=excluded.timezone
            """, (interaction.user.id, date, timezone))
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"🎂 Birthday set to '{date}' in timezone '{timezone}'!", ephemeral=True)

    @birthday_group.command(name="remove", description="Remove your saved birthday")
    async def remove_birthday(self, interaction: discord.Interaction):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("DELETE FROM birthdays WHERE user_id = ?", (interaction.user.id,))
        changes = conn.total_changes
        conn.commit()
        conn.close()

        if changes > 0:
            await interaction.response.send_message("Your birthday has been removed.", ephemeral=True)
        else:
            await interaction.response.send_message("You don't have a birthday set.", ephemeral=True)

    @birthday_group.command(name="list", description="List all birthdays for a specific month")
    @app_commands.describe(month="Specify a month (1-12) to see birthdays for that month")
    async def list_birthdays(self, interaction: discord.Interaction, month: int):
        if month < 1 or month > 12:
            await interaction.response.send_message("Invalid month! Please use a number between 1 and 12.", ephemeral=True)
            return

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT user_id, birthday FROM birthdays")
        rows = c.fetchall()
        conn.close()

        if not rows:
            await interaction.response.send_message("No birthdays have been set yet!", ephemeral=True)
            return

        now = datetime.now(timezone.utc)
        birthdays_list = []
        for user_id, date_str in rows:
            bday_month, day = map(int, date_str.split("-"))
            if bday_month == month:
                display_date = datetime(now.year, bday_month, day, tzinfo=timezone.utc)
                birthdays_list.append((user_id, display_date, day))
        
        if not birthdays_list:
            month_name = datetime(now.year, month, 1).strftime('%B')
            await interaction.response.send_message(f"No birthdays in {month_name}!", ephemeral=True)
            return
        
        # Sort by day of month
        birthdays_list.sort(key=lambda x: x[2])
        month_name = datetime(now.year, month, 1).strftime('%B')
        
        lines = []
        for user_id, date, _ in birthdays_list:
            user = interaction.guild.get_member(user_id)
            name = user.display_name if user else f"User {user_id}"
            lines.append(f"**{name}** - {date.strftime('%B %d')}")
        
        embed = discord.Embed(
            title=f"🎂 Birthdays in {month_name}",
            description="\n".join(lines),
            color=discord.Color.magenta()
        )
        await interaction.response.send_message(embed=embed)

    @birthday_group.command(name="channel", description="Set the channel for birthday announcements")
    @app_commands.describe(channel="Channel where birthday announcements will be sent")
    @ModerationBase.is_admin()
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
                    INSERT INTO guild_settings (guild_id, channel_id)
                    VALUES (?, ?)
                    ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id
                    """, (interaction.guild.id, channel.id))
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"Birthday announcements will be sent in {channel.mention}")

    @tasks.loop(minutes=1)
    async def check_birthdays(self):
        now_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT user_id, birthday, timezone FROM birthdays")
        users = c.fetchall()

        for user_id, date_str, timezone_str in users:
            try:
                tz = pytz.timezone(timezone_str)
            except pytz.UnknownTimeZoneError:
                continue

            now_local = datetime.now(pytz.utc).astimezone(tz)
            if now_local.hour == 0 and now_local.minute == 0:
                month, day = map(int, date_str.split("-"))
                if month == now_local.month and day == now_local.day:
                    for guild in self.bot.guilds:
                        member = guild.get_member(user_id)
                        if not member:
                            continue

                        c.execute("SELECT channel_id FROM guild_settings WHERE guild_id=?", (guild.id,))
                        row = c.fetchone()
                        if not row:
                            continue
                        channel_id = row[0]
                        channel = guild.get_channel(channel_id)
                        
                        if channel:
                            try:
                                # Send birthday message
                                await channel.send(f"🎉 Happy Birthday, {member.mention}! 🎂")
                                
                                # Grant birthday role
                                role = guild.get_role(BIRTHDAY_ROLE_ID)
                                if role and role not in member.roles:
                                    await member.add_roles(role)
                                    
                                    # Record role grant in database
                                    granted_at = datetime.now(timezone.utc).isoformat()
                                    c.execute("""
                                        INSERT INTO active_birthday_roles (user_id, guild_id, granted_at)
                                        VALUES (?, ?, ?)
                                        ON CONFLICT(user_id, guild_id) DO UPDATE SET granted_at=excluded.granted_at
                                    """, (user_id, guild.id, granted_at))
                                    conn.commit()
                            except Exception:
                                pass

        conn.close()
    
    @tasks.loop(minutes=5)
    async def remove_birthday_roles(self):
        """Remove birthday roles after 24 hours."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT user_id, guild_id, granted_at FROM active_birthday_roles")
        active_roles = c.fetchall()
        
        now = datetime.now(timezone.utc)
        
        for user_id, guild_id, granted_at_str in active_roles:
            granted_at = datetime.fromisoformat(granted_at_str)
            
            # Check if 24 hours have passed
            if now - granted_at >= timedelta(hours=24):
                guild = self.bot.get_guild(guild_id)
                if guild:
                    member = guild.get_member(user_id)
                    if member:
                        role = guild.get_role(BIRTHDAY_ROLE_ID)
                        if role and role in member.roles:
                            try:
                                await member.remove_roles(role)
                            except Exception:
                                pass
                
                # Remove from database
                c.execute("DELETE FROM active_birthday_roles WHERE user_id=? AND guild_id=?", (user_id, guild_id))
                conn.commit()
        
        conn.close()

    @check_birthdays.before_loop
    async def before_check_birthdays(self):
        await self.bot.wait_until_ready()
    
    @remove_birthday_roles.before_loop
    async def before_remove_birthday_roles(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Birthday(bot))