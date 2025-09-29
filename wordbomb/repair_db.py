import sqlite3
import os
from pathlib import Path

def repair_database():
    db_path = Path(__file__).parent / 'wordbomb.db'
    print(f"Repairing database at: {db_path}")
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Create tables if they don't exist
    c.executescript("""
    BEGIN TRANSACTION;
    
    CREATE TABLE IF NOT EXISTS guilds (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        channel_id INTEGER NOT NULL,
        last_word TEXT NOT NULL DEFAULT '',
        last_substring TEXT NOT NULL DEFAULT ''
    );
    
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL
    );
    
    CREATE TABLE IF NOT EXISTS scores (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        guild_id INTEGER NOT NULL,
        score INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (guild_id) REFERENCES guilds(id)
    );
    
    COMMIT;
    """)
    
    # Verify tables were created
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = c.fetchall()
    print("Tables in database:", [table[0] for table in tables])
    
    conn.commit()
    conn.close()
    print("Database repair complete!")

if __name__ == '__main__':
    repair_database()