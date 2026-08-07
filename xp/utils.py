import math
import random
import time
import discord
from discord.utils import get

COOLDOWN = 60

ROLE_REWARDS = {
    2: 963498974222885054,
    8: 1372088164377694208,
    100: 1296055376009101384,
    150: 1296056209543008287,
    200: 1296056657784340480
}

MULTIPLIERS = {
    1038402681376612413: 1.25,
    1213171315259736155: 1.25,
    881560923494547477: 1.5,
    1008830505166323742: 1.5,
    880055414434201600: 1.5,
    931234149774270524: 2,
    1238966782962958377: 2.5,
    1113751318918602762: 3,
    1528850322292736030: 3
}

XP_CURVE = {
    "base": 1,
    "square": 50,
    "linear": 100,
    "divisor": 1
}

RANDOM_XP = {
    "min": 50,
    "max": 100
}

def load_config():
    """Load configuration (returns the hardcoded config dict)"""
    return {
        "cooldown": COOLDOWN,
        "role_rewards": ROLE_REWARDS,
        "multipliers": MULTIPLIERS,
        "xp_curve": XP_CURVE,
        "random_xp": RANDOM_XP
    }

def get_multiplier(member, apply_multiplier=True):
    """Get XP multiplier for a member based on their roles"""
    if not apply_multiplier:
        return 1
    
    # Ensure we have a Member object with roles
    if not isinstance(member, discord.Member):
        return 1
    
    highest = 1
    
    for role in member.roles:
        if role.id in MULTIPLIERS:
            highest = max(highest, MULTIPLIERS[role.id])
    
    return highest

def xp_for_level(level: int) -> int:
    """Calculate total XP required to reach a given level"""
    xp = (level ** 3 * XP_CURVE["base"]) + (level ** 2 * XP_CURVE["square"]) + (level * XP_CURVE["linear"])
    xp = xp / XP_CURVE["divisor"]
    return int(math.floor(xp / 100) * 100)

def random_xp() -> int:
    """Generate random XP amount within configured range"""
    return random.randint(RANDOM_XP["min"], RANDOM_XP["max"])

def can_get_xp(last_message_time: int) -> bool:
    """Check if enough time has passed since last XP gain"""
    # FIXED: This function should ONLY check cooldown, not access member.roles
    return (time.time() - last_message_time) >= COOLDOWN

async def check_level_up(member, cur, conn, lifetime=True):
    """Check if member leveled up and grant role rewards"""
    # Ensure we have a Member object
    if not isinstance(member, discord.Member):
        return
    
    cur.execute("SELECT xp, level FROM xp WHERE user_id = ?", (str(member.id),))
    row = cur.fetchone()
    if not row:
        return
    
    xp, level = row
    new_level = level
    
    while xp >= xp_for_level(new_level + 1):
        new_level += 1
    
    if new_level > level:
        cur.execute("UPDATE xp SET level = ? WHERE user_id = ?", (new_level, str(member.id)))
        conn.commit()
        
        if lifetime:
            # Grant all roles for levels they've reached
            for lvl, role_id in ROLE_REWARDS.items():
                if new_level >= lvl:
                    role = get(member.guild.roles, id=role_id)
                    if role and role not in member.roles:
                        await member.add_roles(role)