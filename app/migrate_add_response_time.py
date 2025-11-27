import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "srp_chatbot.db")
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Add the column only if it doesn't exist yet
cur.execute("PRAGMA table_info(chat_logs);")
cols = [row[1] for row in cur.fetchall()]
if "response_time_ms" not in cols:
    cur.execute("ALTER TABLE chat_logs ADD COLUMN response_time_ms INTEGER;")
    conn.commit()
    print("Added response_time_ms column.")
else:
    print("response_time_ms already exists, nothing to do.")

conn.close()
