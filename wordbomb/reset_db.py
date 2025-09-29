import sqlite3
import os

def reset_database():
    db_path = os.path.join(os.path.dirname(__file__), 'wordbomb.db')
    
    # Remove existing database if it exists
    if os.path.exists(db_path):
        os.remove(db_path)
    
    # Create fresh database with proper permissions
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        c.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        
        CREATE TABLE guilds (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            last_word TEXT NOT NULL DEFAULT '',
            last_substring TEXT NOT NULL DEFAULT ''
        );
        
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        
        CREATE TABLE scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, guild_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (guild_id) REFERENCES guilds(id)
        );
        """)
        
        conn.commit()
        print(f"Database created successfully with proper permissions")
        
    except Exception as e:
        print(f"Error creating database: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    reset_database()