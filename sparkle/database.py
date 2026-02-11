import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "sparkle.db")

def get_db():
    """Return a SQLite3 connection with initialized tables."""
    conn = sqlite3.connect(DB_PATH)
    
    # Create sparkles table
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
    
    # Create sparkle_events table for tracking individual sparkle occurrences
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
    
    # Create index for faster queries
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sparkle_events_server 
        ON sparkle_events(server_id, timestamp)
    """)
    
    conn.commit()
    return conn