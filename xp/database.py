import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_db(lifetime=True):
    db_name = "lifetime.db" if lifetime else "annual.db"
    db_path = os.path.join(BASE_DIR, db_name)
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
    conn.commit()
    return conn, cur
