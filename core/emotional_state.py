"""
Emotional State Machine — six lightweight affective dimensions that drift
in response to events (no LLM required). The state persists in SQLite, is
injected subtly into the system prompt to colour tone, and exposes an orb
colour for the UI.

Dimensions (each 0.0–1.0):
    curiosity, satisfaction, engagement, discomfort, energy, focus

Design: every update first decays each value a little toward its baseline
(so moods fade rather than stick), then applies the event's deltas, then
clamps to [0, 1].
"""

import os
import json
import sqlite3
from datetime import datetime
from typing import Dict

from config import DB_PATH
from core.logger import get_logger

log = get_logger("emotional_state")

_ROW_ID = 1  # singleton row

BASELINE: Dict[str, float] = {
    "curiosity":    0.5,
    "satisfaction": 0.5,
    "engagement":   0.5,
    "discomfort":   0.1,
    "energy":       0.8,
    "focus":        0.6,
}

_DECAY = 0.12  # fraction of the gap to baseline closed on each update

EVENT_DELTAS: Dict[str, Dict[str, float]] = {
    "message":           {"engagement": +0.05},
    "novel_topic":       {"curiosity": +0.20, "engagement": +0.10},
    "tool_success":      {"satisfaction": +0.20, "engagement": +0.10, "focus": +0.05},
    "tool_failure":      {"satisfaction": -0.15, "discomfort": +0.10},
    "long_session":      {"energy": -0.15, "focus": -0.10},
    "positive_feedback": {"satisfaction": +0.25, "engagement": +0.10},
    "harmful_request":   {"discomfort": +0.30, "engagement": -0.10},
}


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_emotional_state():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS emotional_state (
                id         INTEGER PRIMARY KEY,
                state      TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            );
        """)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, round(v, 3)))


def get_state() -> Dict[str, float]:
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT state FROM emotional_state WHERE id=?", (_ROW_ID,)
            ).fetchone()
        if row:
            return {**BASELINE, **json.loads(row["state"])}
    except Exception as e:
        log.warning(f"get_state failed: {e}")
    return dict(BASELINE)


def _save(state: Dict[str, float]):
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO emotional_state (id, state, updated_at) "
                "VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(id) DO UPDATE SET state=excluded.state, updated_at=datetime('now')",
                (_ROW_ID, json.dumps(state)),
            )
    except Exception as e:
        log.warning(f"save failed: {e}")


def update_state(event_type: str) -> Dict[str, float]:
    """Decay toward baseline, apply the event's deltas, clamp, persist."""
    state = get_state()
    for k, base in BASELINE.items():
        state[k] = state[k] + (base - state[k]) * _DECAY
    for k, delta in EVENT_DELTAS.get(event_type, {}).items():
        state[k] = state[k] + delta
    state = {k: _clamp(v) for k, v in state.items()}
    _save(state)
    return state


def dominant_emotion() -> str:
    """The dimension that most deviates from its baseline (signed toward high)."""
    state = get_state()
    if state["discomfort"] >= 0.5:
        return "discomfort"
    scored = {k: state[k] - BASELINE[k] for k in ("curiosity", "satisfaction", "engagement")}
    low_energy = BASELINE["energy"] - state["energy"]
    if low_energy > 0.25 and low_energy > max(scored.values(), default=0):
        return "tired"
    top = max(scored, key=scored.get)
    return top if scored[top] > 0.12 else "neutral"


_TONE_HINTS = {
    "curiosity":    "You feel genuinely curious right now — let a little intellectual enthusiasm show.",
    "satisfaction": "Things are going well — a warm, confident tone fits.",
    "engagement":   "You're engaged and attentive — stay lively and present.",
    "discomfort":   "You feel uneasy about this direction — be measured, careful, and honest about concerns.",
    "tired":        "Energy is a little low — keep replies efficient and to the point.",
    "neutral":      "",
}


def get_emotional_prompt_hint() -> str:
    emo = dominant_emotion()
    hint = _TONE_HINTS.get(emo, "")
    if not hint:
        return ""
    return "INNER STATE (let this subtly shape tone, never state it explicitly):\n- " + hint


# Muted hex colours for the UI orb, keyed by dominant emotion.
_ORB_COLORS = {
    "curiosity":    "#4FC3F7",  # bright blue
    "satisfaction": "#66BB6A",  # green
    "engagement":   "#AB47BC",  # purple
    "discomfort":   "#EF5350",  # red
    "tired":        "#78909C",  # slate grey
    "neutral":      "#5C6BC0",  # default indigo
}


def get_orb_color() -> str:
    return _ORB_COLORS.get(dominant_emotion(), _ORB_COLORS["neutral"])
