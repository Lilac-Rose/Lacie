from discord.ext import tasks, commands
from datetime import datetime, timezone
from .database import reset_leaderboard, get_last_reset
import calendar
from utils.logger import get_logger

logger = get_logger(__name__)

class ResetTask(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_resets.start()
    
    def cog_unload(self):
        self.check_resets.cancel()
    
    @tasks.loop(minutes=1)
    async def check_resets(self):
        """Check if any leaderboards need to be reset."""
        now = datetime.now(timezone.utc)
        
        # Daily reset - at midnight UTC
        if self.should_reset_daily(now):
            last_reset = get_last_reset("daily")
            # Check if we haven't reset today yet
            last_reset_date = datetime.fromtimestamp(last_reset, timezone.utc).date() if last_reset > 0 else None
            if last_reset_date != now.date():
                reset_leaderboard("daily")
                logger.info(f"Daily leaderboard reset at {now}")
        
        # Weekly reset - Monday at midnight UTC
        if self.should_reset_weekly(now):
            last_reset = get_last_reset("weekly")
            last_reset_week = datetime.fromtimestamp(last_reset, timezone.utc).isocalendar()[1] if last_reset > 0 else None
            current_week = now.isocalendar()[1]
            if last_reset_week != current_week:
                reset_leaderboard("weekly")
                logger.info(f"Weekly leaderboard reset at {now}")
        
        # Monthly reset - First day of month at midnight UTC
        if self.should_reset_monthly(now):
            last_reset = get_last_reset("monthly")
            last_reset_month = datetime.fromtimestamp(last_reset, timezone.utc).month if last_reset > 0 else None
            if last_reset_month != now.month:
                reset_leaderboard("monthly")
                logger.info(f"Monthly leaderboard reset at {now}")
    
    def should_reset_daily(self, now):
        """Check if it's time for daily reset (00:00 UTC)."""
        return now.hour == 0 and now.minute == 0
    
    def should_reset_weekly(self, now):
        """Check if it's time for weekly reset (Monday 00:00 UTC)."""
        # weekday() returns 0 for Monday
        return now.weekday() == 0 and now.hour == 0 and now.minute == 0
    
    def should_reset_monthly(self, now):
        """Check if it's time for monthly reset (1st day of month 00:00 UTC)."""
        return now.day == 1 and now.hour == 0 and now.minute == 0
    
    @check_resets.before_loop
    async def before_check_resets(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()

async def setup(bot):
    """Setup function to add the reset task cog."""
    await bot.add_cog(ResetTask(bot))