import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "profile.db"

def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def setup_db():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS profiles (
        user_id INTEGER PRIMARY KEY,
        pronouns TEXT,
        about_me TEXT,
        fav_color TEXT,
        bg_color TEXT,
        fav_game TEXT,
        fav_artist TEXT,
        birthday TEXT,
        font_name TEXT
    )
    """)
    db.commit()
    db.close()