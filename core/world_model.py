"""
World Model — a live, structured working state of what Aria is currently
helping with. Distinct from episodic memory (a log) and semantic memory
(durable facts): this is a small mutable snapshot injected into the system
prompt so Aria stays oriented across turns.

Stored as a single-row JSON blob in the `world_model` SQLite table.
Updated after conversations via a lightweight, low-temperature LLM extraction.
"""

import os
import json
import sqlite3
import requests
from datetime import datetime
from typing import Dict, List

from config import DB_PATH
import config as cfg
from core.logger import get_logger

log = get_logger("world_model")

_ROW_ID = 1  # singleton row

DEFAULT_STATE: Dict = {
    "current_task":      "",
    "open_problems":     [],
    "pending_followups": [],
    "recent_topics":     [],
    "inferred_mood":     "neutral",
    "last_updated":      "",
}

_MAX_LIST = 6  # cap each list so the prompt section stays small


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_world_model():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS world_model (
                id         INTEGER PRIMARY KEY,
                state      TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            );
        """)


def get_state() -> Dict:
    """Return the current world-model state, falling back to defaults."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT state FROM world_model WHERE id=?", (_ROW_ID,)
            ).fetchone()
        if row:
            state = json.loads(row["state"])
            return {**DEFAULT_STATE, **state}
    except Exception as e:
        log.warning(f"get_state failed: {e}")
    return dict(DEFAULT_STATE)


def save_state(state: Dict):
    merged = {**DEFAULT_STATE, **state}
    merged["last_updated"] = datetime.now().isoformat(timespec="seconds")
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO world_model (id, state, updated_at) VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(id) DO UPDATE SET state=excluded.state, updated_at=datetime('now')",
                (_ROW_ID, json.dumps(merged)),
            )
    except Exception as e:
        log.warning(f"save_state failed: {e}")


def _dedup_cap(items: List[str]) -> List[str]:
    seen, out = set(), []
    for it in items:
        it = str(it).strip()
        key = it.lower()
        if it and key not in seen:
            seen.add(key)
            out.append(it)
    return out[:_MAX_LIST]


def get_world_model_for_prompt() -> str:
    """Format the world model as a compact 'Current context' prompt section."""
    s = get_state()
    if not any([s["current_task"], s["open_problems"],
                s["pending_followups"], s["recent_topics"]]):
        return ""
    lines = ["Current context (live working model):"]
    if s["current_task"]:
        lines.append(f"- Current task: {s['current_task']}")
    if s["open_problems"]:
        lines.append("- Open problems: " + "; ".join(s["open_problems"]))
    if s["pending_followups"]:
        lines.append("- Pending follow-ups: " + "; ".join(s["pending_followups"]))
    if s["recent_topics"]:
        lines.append("- Recent topics: " + ", ".join(s["recent_topics"]))
    if s["inferred_mood"] and s["inferred_mood"] != "neutral":
        lines.append(f"- Inferred user mood: {s['inferred_mood']}")
    return "\n".join(lines)


_EXTRACT_SYSTEM = (
    "You maintain a compact working model of an assistant's session with a user. "
    "Given the PREVIOUS state and the latest exchange, return the UPDATED state "
    "as strict JSON with exactly these keys: current_task (string), "
    "open_problems (array of short strings), pending_followups (array of short "
    "strings), recent_topics (array of short strings), inferred_mood (single word). "
    "Carry forward anything still relevant, drop what is resolved, and keep each "
    "array to at most 6 short items. Respond with JSON only — no prose, no code fences."
)


def update_from_conversation(user_message: str, assistant_reply: str) -> Dict:
    """Refresh the world model from the latest exchange via a small LLM call.

    Best-effort: on any failure the previous state is preserved and returned.
    """
    prev = get_state()
    prompt = (
        f"PREVIOUS STATE:\n{json.dumps({k: prev[k] for k in DEFAULT_STATE if k != 'last_updated'})}\n\n"
        f"LATEST EXCHANGE:\nUser: {user_message[:600]}\n"
        f"Assistant: {assistant_reply[:600]}\n\n"
        "Return the updated state as JSON only."
    )
    try:
        r = requests.post(
            f"{cfg.get('ollama_base_url')}/api/chat",
            json={
                "model":    cfg.get("model_fast") or cfg.get("ollama_model"),
                "system":   _EXTRACT_SYSTEM,
                "messages": [{"role": "user", "content": prompt}],
                "stream":   False,
                "format":   "json",
                "options":  {"temperature": 0.3, "num_ctx": 4096},
            },
            timeout=60,
        )
        r.raise_for_status()
        raw = r.json()["message"]["content"].strip()
        data = json.loads(raw)
    except Exception as e:
        log.warning(f"update_from_conversation failed, keeping prior state: {e}")
        return prev

    new_state = {
        "current_task":      str(data.get("current_task", prev["current_task"]) or "").strip(),
        "open_problems":     _dedup_cap(data.get("open_problems", prev["open_problems"]) or []),
        "pending_followups": _dedup_cap(data.get("pending_followups", prev["pending_followups"]) or []),
        "recent_topics":     _dedup_cap(data.get("recent_topics", prev["recent_topics"]) or []),
        "inferred_mood":     str(data.get("inferred_mood", prev["inferred_mood"]) or "neutral").strip().split()[0].lower(),
    }
    save_state(new_state)
    log.info(f"World model updated: task='{new_state['current_task'][:60]}' mood={new_state['inferred_mood']}")
    return new_state
