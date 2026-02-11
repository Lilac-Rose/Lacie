import time
import discord
from .database import get_db
from .utils import get_multiplier, random_xp, can_get_xp, check_level_up
from .exclude_channels import is_channel_excluded

async def add_xp(user):
    # Only process XP for guild members, not DM users
    if not isinstance(user, discord.Member):
        return
    
    member = user
    
    # Check if message is in an excluded channel
    if hasattr(member, "guild"):
        last_message = getattr(member, "last_message", None)
        if last_message and getattr(last_message, "channel", None):
            if is_channel_excluded(last_message.channel.id):
                return
    
    conn_check, cur_check = get_db("lifetime")
    cur_check.execute("SELECT last_message FROM xp WHERE user_id = ?", (str(member.id),))
    row_check = cur_check.fetchone()
    conn_check.close()
    
    if row_check and not can_get_xp(row_check[0]):
        return  # Still on cooldown, don't add XP to any database
    
    base_xp = random_xp()
    
    leaderboard_types = [
        ("lifetime", True),   # (db_type, apply_multiplier)
        ("annual", False),
        ("monthly", False),
        ("weekly", False),
        ("daily", False)
    ]
    
    for db_type, apply_multiplier in leaderboard_types:
        conn, cur = get_db(db_type)
        cur.execute("SELECT xp, level, last_message FROM xp WHERE user_id = ?", (str(member.id),))
        row = cur.fetchone()
        
        if row:
            xp, level, last_msg = row
        else:
            xp, level, last_msg = (0, 0, 0)
            cur.execute(
                "INSERT INTO xp (user_id, xp, level, last_message) VALUES (?, ?, ?, ?)",
                (str(member.id), 0, 0, 0)
            )
        
        # Only apply multiplier for lifetime XP
        gained = int(base_xp * get_multiplier(member, apply_multiplier=apply_multiplier))
        new_xp = xp + gained
        
        cur.execute(
            "UPDATE xp SET xp = ?, last_message = ? WHERE user_id = ?",
            (new_xp, int(time.time()), str(member.id))
        )
        conn.commit()
        
        await check_level_up(member, cur, conn, db_type == "lifetime")
        conn.close()