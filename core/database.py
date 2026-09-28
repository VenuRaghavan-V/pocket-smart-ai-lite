"""
core/database.py
-----------------
All SQLite logic lives here. Every other part of the app talks to the
database only through these functions - so later, if "Notes Manager" or
"Task Manager" need their own tables, you just add new functions here
(or a new file, e.g. core/notes_db.py) without touching app.py routes.

Deploy note: the database file lives at Config.DB_PATH, which points to
the project folder locally and to the OS temp dir on a read-only
serverless host. On Vercel each function instance keeps its own copy,
so history is per-instance and resets when the instance is recycled;
Render (or any always-on host) keeps it for the life of the service.
"""

import os
import sqlite3
from datetime import datetime

from config import Config


def get_connection():
    """Open a new SQLite connection with row access by column name."""
    os.makedirs(os.path.dirname(Config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the chat_history table if it doesn't already exist."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,              -- 'user' or 'assistant'
            message TEXT NOT NULL,
            language TEXT,                   -- 'ta' (Tamil) or 'en' (English)
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def save_message(session_id: str, role: str, message: str, language: str = "en"):
    """Insert one chat message (user or assistant) into history."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO chat_history (session_id, role, message, language, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, role, message, language, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


def get_history(session_id: str, limit: int = 50):
    """Return the most recent messages for a session, oldest first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT role, message, language, created_at FROM chat_history "
        "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, limit)
    ).fetchall()
    conn.close()
    return [dict(row) for row in reversed(rows)]


def clear_history(session_id: str):
    """Wipe chat history for one session (used by the 'New Chat' button)."""
    conn = get_connection()
    conn.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
