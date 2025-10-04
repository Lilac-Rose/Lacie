import math, random, time
from discord.utils import get

# Role rewards for leveling up (only apply to lifetime XP)
ROLE_REWARDS = {
    2: 963498974222885054,
    8: 1372088164377694208,
    100: 1296055376009101384,
    150: 1296056209543008287,
    200: 1296056657784340480,
}

# XP multipliers by role (only apply to lifetime XP)
MULTIPLIERS = {
    "1038402681376612413": 1.25,
    "1213171315259736155": 1.25,
    "881560923494547477": 1.5,
    "1008830505166323742": 1.5,
    "880055414434201600": 1.5,
    "931234149774270524": 2,
    "1238966782962958377": 2.5,
    "1113751318918602762": 3,
}

# Cooldown in seconds between XP gains
COOLDOWN = 60


def get_multiplier(member, apply_multiplier=True):
    """Return XP multiplier from roles, or 1 if multiplier shouldn't be applied."""
    if not apply_multiplier:
        return 1

    highest = 1
    for role in member.roles:
        if str(role.id) in MULTIPLIERS:
            highest = max(highest, MULTIPLIERS[str(role.id)])
    return highest


def xp_for_level(level: int) -> int:
    """Calculate total XP required for a given level."""
    xp = (level ** 3) + (50 * level ** 2) + (100 * level)
    return int(math.floor(xp / 100) * 100)  # round down to nearest 100


def random_xp() -> int:
    """Random XP awarded per message."""
    return random.randint(50, 100)


def can_get_xp(last_message_time: int) -> bool:
    """Check if enough time has passed since last XP gain."""
    return (time.time() - last_message_time) >= COOLDOWN


async def check_level_up(member, cur, conn, lifetime=True):
    """Check if user leveled up and give rewards (only for lifetime XP)."""
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

        # Only assign role rewards for lifetime XP
        if lifetime:
            from discord.utils import get
            for lvl, role_id in ROLE_REWARDS.items():
                if new_level >= lvl:
                    role = get(member.guild.roles, id=role_id)
                    if role:
                        await member.add_roles(role)
