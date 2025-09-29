import json
import sqlite3
import os
from xp.utils import xp_for_level

# path to xp/ folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# JSON lives in xp/
OLD_FILE = os.path.join(BASE_DIR, "Paper_Lily_Fan_Community.json")

# database also in xp/
DB = os.path.join(BASE_DIR, "lifetime.db")

with open(OLD_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

# Get the users dictionary where keys are user IDs and values are user data
users_data = data.get("users", {})

conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS xp (
    user_id TEXT PRIMARY KEY,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 0,
    last_message INTEGER DEFAULT 0
)
""")

for user_id, user_info in users_data.items():
    uid = str(user_id)
    xp = int(user_info.get("xp", 0))
    level = 0
    while xp >= xp_for_level(level + 1):
        level += 1
    cur.execute("INSERT OR REPLACE INTO xp (user_id, xp, level, last_message) VALUES (?, ?, ?, 0)",
                (uid, xp, level))

conn.commit()
conn.close()

print("✅ Import finished into xp/lifetime.db")