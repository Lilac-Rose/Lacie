import math, random, time, json
from discord.utils import get
from pathlib import Path
CONFIG_PATH = Path("/home/lilacrose/lilacrose.dev2.0/bots/lacie/xp_config.json")

def load_config():
    with CONFIG_PATH.open() as f:
        return json.load(f)

def get_multiplier(member, apply_multiplier=True):
    if not apply_multiplier:
        return 1
    config = load_config()
    multipliers = config["MULTIPLIERS"]
    highest = 1
    for role in member.roles:
        if str(role.id) in multipliers:
            highest = max(highest, multipliers[str(role.id)])
    return highest

def xp_for_level(level: int) -> int:
    config = load_config()
    curve = config.get("XP_CURVE", {"base": 1, "square": 50, "linear": 100, "divisor": 100})
    
    xp = (level ** 3 * curve["base"]) + (level ** 2 * curve["square"]) + (level * curve["linear"])
    xp = xp / curve["divisor"]
    return int(math.floor(xp / 100) * 100)

def random_xp() -> int:
    config = load_config()
    xp_range = config.get("RANDOM_XP", {"min": 50, "max": 100})
    return random.randint(xp_range["min"], xp_range["max"])

def can_get_xp(last_message_time: int) -> bool:
    config = load_config()
    cooldown = config["COOLDOWN"]
    return (time.time() - last_message_time) >= cooldown

async def check_level_up(member, cur, conn, lifetime=True):
    config = load_config()
    role_rewards = {int(k): v for k,v in config["ROLE_REWARDS"].items()}
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
            for lvl, role_id in role_rewards.items():
                if new_level >= lvl:
                    role = get(member.guild.roles, id=role_id)
                    if role:
                        await member.add_roles(role)