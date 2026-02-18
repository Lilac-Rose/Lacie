import sqlite3
from pathlib import Path

DB_DIR = Path(__file__).parent.parent / "data"

DB_DIR.mkdir(parents=True, exist_ok=True)

def get_db(db_type="lifetime"):
    if isinstance(db_type, bool):
        db_type = "lifetime" if db_type else "annual"

    valid_types = ["lifetime", "annual", "monthly", "weekly", "daily"]
    if db_type not in valid_types:
        db_type = "lifetime"

    db_name = f"{db_type}.db"
    db_path = str(DB_DIR / db_name)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS xp (
        user_id TEXT PRIMARY KEY,
        xp INTEGER DEFAULT 0,
        level INTEGER DEFAULT 0,
        last_message INTEGER DEFAULT 0
    )
    """)

    if db_type in ["daily", "weekly", "monthly"]:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS reset_log (
            id INTEGER PRIMARY KEY,
            last_reset INTEGER DEFAULT 0
        )
        """)
        cur.execute("INSERT OR IGNORE INTO reset_log (id, last_reset) VALUES (1, 0)")

    conn.commit()
    return conn, cur

def reset_leaderboard(db_type):
    import time

    conn, cur = get_db(db_type)
    cur.execute("DELETE FROM xp")
    cur.execute("UPDATE reset_log SET last_reset = ? WHERE id = 1", (int(time.time()),))
    conn.commit()
    conn.close()

def get_last_reset(db_type):
    conn, cur = get_db(db_type)
    cur.execute("SELECT last_reset FROM reset_log WHERE id = 1")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0
