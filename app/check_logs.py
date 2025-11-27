import os, sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "srp_chatbot.db")
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""
    SELECT timestamp, user_message, assistant_message, response_time_ms
    FROM chat_logs
    ORDER BY id DESC
    LIMIT 5;
""")

for row in cur.fetchall():
    print(row)

conn.close()
