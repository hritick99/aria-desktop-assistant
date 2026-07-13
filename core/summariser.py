"""Auto-compress old conversation turns to keep context quality high."""
import json, sqlite3, requests
from typing import List, Dict, Optional
from core.logger import get_logger
from config import DB_PATH, get
log = get_logger("summariser")
SUMMARISE_AFTER = 30
KEEP_RECENT     = 15

def _conn():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; return conn

def get_summary(sid):
    with _conn() as c:
        r = c.execute("SELECT summary FROM summaries WHERE session_id=?", (sid,)).fetchone()
        return r["summary"] if r else None

def save_summary(sid, summary, count):
    with _conn() as c:
        c.execute("""INSERT INTO summaries (session_id,summary,msg_count)
            VALUES(?,?,?) ON CONFLICT(session_id) DO UPDATE SET
            summary=excluded.summary,msg_count=excluded.msg_count,updated_at=datetime('now')""",
            (sid, summary, count))

def maybe_summarise(session_id, messages):
    if len(messages) < SUMMARISE_AFTER: return messages
    old, recent = messages[:-KEEP_RECENT], messages[-KEEP_RECENT:]
    existing = get_summary(session_id)
    lines = []
    if existing: lines.append(f"Previous summary:\n{existing}\n")
    for m in old: lines.append(f"{'User' if m['role']=='user' else 'Assistant'}: {m['content'][:300]}")
    prompt = "Summarise this conversation concisely, preserving names, numbers, decisions:\n\n" + "\n".join(lines)
    try:
        r = requests.post(f"{get('ollama_base_url')}/api/chat",
            json={"model":get("ollama_model"),"messages":[{"role":"user","content":prompt}],
                  "stream":False,"options":{"temperature":0.3,"num_ctx":2048}}, timeout=60)
        r.raise_for_status()
        summary = r.json()["message"]["content"].strip()
        save_summary(session_id, summary, len(messages))
        log.info(f"Summarised {len(old)} msgs")
        return [{"role":"assistant","content":f"[Summary so far]: {summary}"}] + recent
    except Exception as e:
        log.warning(f"Summarisation failed: {e}")
        return messages

def inject_summary_if_exists(session_id, messages):
    s = get_summary(session_id)
    if s and messages:
        return [{"role":"assistant","content":f"[Previous session]: {s}"}] + messages
    return messages
