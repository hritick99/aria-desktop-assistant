"""
Memory Layer — semantic facts + episodic conversation logs.
"""

import sqlite3
import re
import os
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional

from config import DB_PATH, get
from core.logger import get_logger

log = get_logger("memory")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS semantic_memory (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                fact       TEXT NOT NULL,
                category   TEXT DEFAULT 'general',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS episodes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                date       TEXT NOT NULL,
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                timestamp  TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                date       TEXT NOT NULL,
                summary    TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS summaries (
                session_id TEXT PRIMARY KEY,
                summary    TEXT NOT NULL,
                msg_count  INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT NOT NULL,
                remind_at  TEXT NOT NULL,
                recurrence TEXT DEFAULT 'once',
                days       TEXT DEFAULT '',
                active     INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)


# ── Semantic memory ────────────────────────────────────────────────────────────

def save_fact(fact: str, category: str = "general"):
    existing = get_all_facts()
    fact_lower = fact.lower().strip()
    for row in existing:
        if row["fact"].lower().strip() == fact_lower:
            return
    with _get_conn() as conn:
        conn.execute("INSERT INTO semantic_memory (fact, category) VALUES (?, ?)",
                     (fact.strip(), category))


def delete_fact(fact_id: int):
    with _get_conn() as conn:
        conn.execute("DELETE FROM semantic_memory WHERE id = ?", (fact_id,))


def get_all_facts() -> List[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM semantic_memory ORDER BY updated_at DESC"
        ).fetchall()


def get_facts_for_prompt() -> str:
    facts = get_all_facts()[:get("max_facts")]
    if not facts:
        return ""
    return "What you know about the user:\n" + "\n".join(f"- {r['fact']}" for r in facts)


def extract_and_save_facts(assistant_reply: str, user_message: str):
    for match in re.finditer(r'\[FACT:\s*(.+?)\]', assistant_reply, re.IGNORECASE):
        fact = match.group(1).strip()
        if fact:
            save_fact(fact)

    patterns = [
        (r"i(?:'m| am) (?:a |an )?(.{3,60})",           "identity"),
        (r"i (?:love|like|enjoy|adore|prefer) (.{3,60})", "preference"),
        (r"i (?:hate|dislike|don't like) (.{3,60})",      "preference"),
        (r"my (?:name is|name's) (.{2,40})",              "identity"),
        (r"i work (?:at|for|in) (.{3,60})",               "work"),
        (r"i(?:'m| am) (?:working|based) (?:at|in) (.{3,60})", "work"),
        (r"i (?:live|stay|am based) (?:in|at) (.{3,60})", "location"),
    ]
    for pattern, category in patterns:
        for match in re.finditer(pattern, user_message, re.IGNORECASE):
            groups = match.groups()
            fact_text = " ".join(g for g in groups if g).strip().rstrip(".,!?")
            if 3 < len(fact_text) < 120:
                fact_text = fact_text[0].upper() + fact_text[1:]
                save_fact(fact_text, category)


# ── Episodic memory ────────────────────────────────────────────────────────────

def get_or_create_session(session_id: str) -> str:
    today = date.today().isoformat()
    with _get_conn() as conn:
        if not conn.execute("SELECT session_id FROM sessions WHERE session_id=?",
                            (session_id,)).fetchone():
            conn.execute("INSERT INTO sessions (session_id, date) VALUES (?, ?)",
                         (session_id, today))
    return session_id


def log_message(session_id: str, role: str, content: str):
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO episodes (session_id, date, role, content) VALUES (?, ?, ?, ?)",
            (session_id, date.today().isoformat(), role, content)
        )


def get_session_messages(session_id: str) -> List[Dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM episodes WHERE session_id=? ORDER BY timestamp ASC",
            (session_id,)
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def list_sessions(limit: int = 40) -> List[Dict]:
    """Recent sessions with a preview + message count, newest first.
    Only sessions that actually contain messages are returned."""
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT e.session_id                         AS session_id,
                   COUNT(*)                             AS msgs,
                   MIN(e.timestamp)                     AS started,
                   MAX(e.timestamp)                     AS ended,
                   (SELECT content FROM episodes
                     WHERE session_id = e.session_id AND role='user'
                     ORDER BY timestamp ASC LIMIT 1)    AS first_user
            FROM episodes e
            GROUP BY e.session_id
            ORDER BY ended DESC
            LIMIT ?
        """, (limit,)).fetchall()
    out = []
    for r in rows:
        preview = (r["first_user"] or "").strip().replace("\n", " ")
        if len(preview) > 60:
            preview = preview[:60] + "…"
        out.append({
            "session_id": r["session_id"],
            "msgs":       r["msgs"],
            "started":    r["started"],
            "ended":      r["ended"],
            "preview":    preview or "(no user messages)",
        })
    return out


def get_messages_by_date(target_date: str) -> List[Dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content, timestamp FROM episodes WHERE date=? ORDER BY timestamp ASC",
            (target_date,)
        ).fetchall()
    return [{"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]} for r in rows]


def get_episodic_summary_for_prompt(days_back: int = 3) -> str:
    summaries = []
    today = date.today()
    for i in range(1, days_back + 1):
        target = (today - timedelta(days=i)).isoformat()
        label  = "Yesterday" if i == 1 else f"{i} days ago"
        msgs   = get_messages_by_date(target)
        if not msgs:
            continue
        lines = []
        for m in msgs[:20]:
            prefix = "User" if m["role"] == "user" else "Assistant"
            lines.append(f"  {prefix}: {m['content'][:120]}")
        summaries.append(f"{label} ({target}):\n" + "\n".join(lines))
    if not summaries:
        return ""
    return "Recent conversation history:\n" + "\n\n".join(summaries)
