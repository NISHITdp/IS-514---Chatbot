# app/db_utils.py

import os
import sqlite3
from datetime import datetime
import bcrypt   # <-- make sure this import is here

# DB lives next to this file: app/srp_chatbot.db
DB_PATH = os.path.join(os.path.dirname(__file__), "srp_chatbot.db")


def init_db() -> None:
    """Create both chat_logs and user_chat_logs tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # === 1) General (anonymous) chat logs ===
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_logs (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
            language          TEXT,
            intent            TEXT,
            needs_escalation  TEXT,
            portal_link_key   TEXT,
            user_message      TEXT,
            assistant_message TEXT,
            response_time_ms  INTEGER
        );
        """
    )

    # === 2) User-specific chat logs (with name & email) ===
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_chat_logs (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
            language          TEXT,
            intent            TEXT,
            needs_escalation  TEXT,
            portal_link_key   TEXT,
            user_name         TEXT,
            user_email        TEXT,
            user_message      TEXT,
            assistant_message TEXT,
            response_time_ms  INTEGER
        );
        """
    )

    # === 3) Users table (for login / signup) ===
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            user_name     TEXT NOT NULL,
            user_email    TEXT NOT NULL,
            user_password TEXT NOT NULL
        );
        """
    )

    conn.commit()
    conn.close()


def create_user(user_name: str, user_email: str, password: str) -> None:
    """Create a user with a bcrypt-hashed password."""
    # bcrypt.hashpw -> bytes; decode to str so it fits nicely in TEXT column
    hashed_pw = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (user_name, user_email, user_password)
        VALUES (?, ?, ?);
        """,
        (user_name, user_email, hashed_pw),
    )
    conn.commit()
    conn.close()


def log_chat_interaction(
    language: str,
    intent: str,
    needs_escalation: bool,
    portal_link_key: str,
    user_message: str,
    assistant_message: str,
    response_time_ms: int | None = None,
) -> None:
    """Log an anonymous/general interaction into chat_logs."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO chat_logs (
            created_at,
            language,
            intent,
            needs_escalation,
            portal_link_key,
            user_message,
            assistant_message,
            response_time_ms
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            datetime.utcnow().isoformat(timespec="seconds"),
            language,
            intent,
            "true" if needs_escalation else "false",
            portal_link_key or "",
            user_message,
            assistant_message,
            response_time_ms,
        ),
    )

    conn.commit()
    conn.close()


def log_user_chat_interaction(
    user_name: str | None,
    user_email: str | None,
    language: str,
    intent: str,
    needs_escalation: bool,
    portal_link_key: str,
    user_message: str,
    assistant_message: str,
    response_time_ms: int | None = None,
) -> None:
    """Log an interaction that is tied to a (pseudo) user into user_chat_logs."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO user_chat_logs (
            created_at,
            language,
            intent,
            needs_escalation,
            portal_link_key,
            user_name,
            user_email,
            user_message,
            assistant_message,
            response_time_ms
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            datetime.utcnow().isoformat(timespec="seconds"),
            language,
            intent,
            "true" if needs_escalation else "false",
            portal_link_key or "",
            user_name or "",
            user_email or "",
            user_message,
            assistant_message,
            response_time_ms,
        ),
    )

    conn.commit()
    conn.close()
