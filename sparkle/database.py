"""Sparkle currency database helpers for the sparkle economy."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "sparkle.db"

def get_db():
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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sparkle_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            sparkle_type TEXT NOT NULL,
            message_id TEXT NOT NULL,
            timestamp INTEGER NOT NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sparkle_events_server 
        ON sparkle_events(server_id, timestamp)
    """)
    
    conn.commit()
    return conn