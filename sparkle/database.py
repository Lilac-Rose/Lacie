import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "sparkle.db")

def get_db():
    """Return a SQLite3 connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sparkles (
            server_id TEXT,
            user_id TEXT,
            epic INTEGER DEFAULT 0,
            rare INTEGER DEFAULT 0,
            regular INTEGER DEFAULT 0,
            PRIMARY KEY (server_id, user_id)
        )
    """)
    conn.commit()
    return conn