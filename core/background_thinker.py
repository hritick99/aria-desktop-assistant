"""
Background Thinker — autonomous, low-frequency reflection.

While the user is idle, Aria periodically reviews her world model, recent
facts, and recent conversation, then produces a single private "thought":
an observation, a noticed pattern, or a proactive idea. Thoughts are stored
in the `thoughts` table; only sufficiently important ones are surfaced to the
user via the proactive suggestion callback.

Uses a lightweight prompt (not the full system prompt) and low temperature
for focused, non-rambling analysis.
"""

import os
import json
import time
import sqlite3
import threading
import requests
from datetime import datetime
from typing import Callable, List, Dict

from config import DB_PATH
import config as cfg
from core.logger import get_logger
from core.memory import get_facts_for_prompt, get_episodic_summary_for_prompt
from core.world_model import get_world_model_for_prompt

log = get_logger("background_thinker")

CHECK_INTERVAL   = 60          # seconds between idle checks
IDLE_BEFORE      = 5 * 60      # user must be idle this long before thinking
MIN_THINK_GAP    = 35 * 60     # minimum seconds between reflection cycles
MIN_SURFACE_GAP  = 45 * 60     # minimum seconds between surfaced thoughts
ACTIVE_HOURS     = range(9, 23)
SURFACE_THRESHOLD = 0.7        # importance needed to interrupt the user


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_thoughts_table():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS thoughts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                kind       TEXT DEFAULT 'observation',
                content    TEXT NOT NULL,
                importance REAL DEFAULT 0.0,
                surfaced   INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)


def _save_thought(kind: str, content: str, importance: float, surfaced: bool):
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO thoughts (kind, content, importance, surfaced) VALUES (?, ?, ?, ?)",
                (kind, content, round(float(importance), 3), 1 if surfaced else 0),
            )
    except Exception as e:
        log.warning(f"save thought failed: {e}")


def get_recent_thoughts(limit: int = 10) -> List[Dict]:
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT kind, content, importance, surfaced, created_at "
                "FROM thoughts ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        log.warning(f"get thoughts failed: {e}")
        return []


_THINK_SYSTEM = (
    "You are the quiet background mind of an assistant. You are NOT talking to "
    "the user right now — you are reflecting privately. Given the recent context, "
    "produce ONE genuinely useful thought: an observation, a pattern you notice, "
    "or a proactive idea that would help the user. Be specific and grounded in the "
    "context; never invent facts. Return strict JSON with keys: kind (one of "
    "'observation','pattern','idea','followup'), thought (under 220 chars, written "
    "as something you could later say to the user), importance (0.0-1.0, how much it "
    "would help), surface (boolean, true only if it is genuinely worth interrupting "
    "the user). JSON only — no prose, no code fences."
)


class BackgroundThinker:
    def __init__(self, on_thought: Callable[[str, str], None]):
        self.on_thought   = on_thought
        self._running     = False
        self._last_activity = time.time()
        self._last_think    = 0.0
        self._last_surface  = 0.0
        self._thread        = None

    def start(self):
        init_thoughts_table()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="background_thinker")
        self._thread.start()
        log.info("Background thinker started")

    def ping(self):
        """Call on user activity — resets the idle timer."""
        self._last_activity = time.time()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            time.sleep(CHECK_INTERVAL)
            try:
                now = time.time()
                idle_for = now - self._last_activity
                if idle_for < IDLE_BEFORE:
                    continue
                if now - self._last_think < MIN_THINK_GAP:
                    continue
                if datetime.now().hour not in ACTIVE_HOURS:
                    continue
                self._last_think = now
                self._think()
            except Exception as e:
                log.warning(f"think loop error: {e}")

    def _gather_context(self) -> str:
        parts = []
        world = get_world_model_for_prompt()
        if world: parts.append(world)
        facts = get_facts_for_prompt()
        if facts: parts.append(facts)
        episodic = get_episodic_summary_for_prompt(days_back=2)
        if episodic: parts.append(episodic)
        return "\n\n".join(parts).strip()

    def _think(self):
        context = self._gather_context()
        if not context:
            log.info("Nothing to reflect on yet")
            return
        try:
            r = requests.post(
                f"{cfg.get('ollama_base_url')}/api/chat",
                json={
                    "model":    cfg.get("model_fast") or cfg.get("ollama_model"),
                    "system":   _THINK_SYSTEM,
                    "messages": [{"role": "user", "content": f"Recent context:\n{context}\n\nReflect and return one thought as JSON."}],
                    "stream":   False,
                    "format":   "json",
                    "options":  {"temperature": 0.3, "num_ctx": 4096},
                },
                timeout=90,
            )
            r.raise_for_status()
            data = json.loads(r.json()["message"]["content"].strip())
        except Exception as e:
            log.warning(f"reflection call failed: {e}")
            return

        thought = str(data.get("thought", "")).strip()
        if not thought:
            return
        kind       = str(data.get("kind", "observation")).strip().lower()
        importance = float(data.get("importance", 0.0) or 0.0)
        wants      = bool(data.get("surface", False))

        now = time.time()
        surface = (wants and importance >= SURFACE_THRESHOLD
                   and now - self._last_surface >= MIN_SURFACE_GAP)

        _save_thought(kind, thought, importance, surface)
        log.info(f"Thought [{kind}] imp={importance:.2f} surface={surface}: {thought[:80]}")

        if surface:
            self._last_surface = now
            try:
                self.on_thought(f"💭 {thought}", "thought")
            except Exception as e:
                log.warning(f"surface callback failed: {e}")
