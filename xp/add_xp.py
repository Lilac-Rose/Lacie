import time
from .database import get_db
from .utils import get_multiplier, random_xp, can_get_xp, check_level_up

async def add_xp(member):
    for lifetime in (True, False):  # True = lifetime, False = annual
        conn, cur = get_db(lifetime)
        cur.execute("SELECT xp, level, last_message FROM xp WHERE user_id = ?", (str(member.id),))
        row = cur.fetchone()

        if row:
            xp, level, last_msg = row
            if not can_get_xp(last_msg):
                conn.close()
                continue
        else:
            xp, level, last_msg = (0, 0, 0)
            cur.execute(
                "INSERT INTO xp (user_id, xp, level, last_message) VALUES (?, ?, ?, ?)",
                (str(member.id), 0, 0, 0)
            )

        # Only apply multiplier for lifetime XP
        gained = int(random_xp() * get_multiplier(member, apply_multiplier=lifetime))
        new_xp = xp + gained

        cur.execute(
            "UPDATE xp SET xp = ?, last_message = ? WHERE user_id = ?",
            (new_xp, int(time.time()), str(member.id))
        )
        conn.commit()

        await check_level_up(member, cur, conn, lifetime)
        conn.close()
