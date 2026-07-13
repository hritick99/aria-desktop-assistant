"""
Knowledge graph memory for Aria.

A structured memory that complements the flat fact list: entities (people,
projects, devices, places, preferences…), free-form observations attached
to each, and typed relations between them. It is populated automatically in
the background from conversations (cheap local model), injected compactly
into Aria's system prompt, and visualised in the Memory panel.

Stored in the same SQLite DB as the rest of Aria's memory.
"""

import json
import re
import sqlite3
import threading
from datetime import datetime

import config as cfg
from config import DB_PATH
from core.logger import get_logger

log = get_logger("kg")

_TYPES = {"person", "project", "device", "place", "organization",
          "preference", "event", "concept", "skill"}
_lock = threading.Lock()


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_kg():
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS kg_entities (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL COLLATE NOCASE,
                type       TEXT DEFAULT 'concept',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(name COLLATE NOCASE)
            );
            CREATE TABLE IF NOT EXISTS kg_observations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id  INTEGER NOT NULL,
                content    TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(entity_id, content COLLATE NOCASE)
            );
            CREATE TABLE IF NOT EXISTS kg_relations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                src        TEXT NOT NULL COLLATE NOCASE,
                rel        TEXT NOT NULL,
                dst        TEXT NOT NULL COLLATE NOCASE,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(src COLLATE NOCASE, rel COLLATE NOCASE, dst COLLATE NOCASE)
            );
        """)


# ── writes ──────────────────────────────────────────────────────────────────

def add_entity(name: str, etype: str = "concept") -> int:
    name = (name or "").strip()
    if not name:
        return 0
    etype = (etype or "concept").strip().lower()
    if etype not in _TYPES:
        etype = "concept"
    with _lock, _conn() as c:
        row = c.execute("SELECT id FROM kg_entities WHERE name=? COLLATE NOCASE",
                        (name,)).fetchone()
        if row:
            c.execute("UPDATE kg_entities SET updated_at=datetime('now') WHERE id=?",
                      (row["id"],))
            return row["id"]
        cur = c.execute("INSERT INTO kg_entities (name, type) VALUES (?, ?)",
                        (name, etype))
        return cur.lastrowid


def add_observation(entity: str, content: str, etype: str = "concept"):
    content = (content or "").strip()
    if not content:
        return
    eid = add_entity(entity, etype)
    if not eid:
        return
    with _lock, _conn() as c:
        try:
            c.execute("INSERT INTO kg_observations (entity_id, content) VALUES (?, ?)",
                      (eid, content))
        except sqlite3.IntegrityError:
            pass


def add_relation(src: str, rel: str, dst: str):
    src, rel, dst = (src or "").strip(), (rel or "").strip(), (dst or "").strip()
    if not (src and rel and dst) or src.lower() == dst.lower():
        return
    add_entity(src); add_entity(dst)
    with _lock, _conn() as c:
        try:
            c.execute("INSERT INTO kg_relations (src, rel, dst) VALUES (?, ?, ?)",
                      (src, rel, dst))
        except sqlite3.IntegrityError:
            pass


def delete_entity(name: str):
    with _lock, _conn() as c:
        row = c.execute("SELECT id FROM kg_entities WHERE name=? COLLATE NOCASE",
                        (name,)).fetchone()
        if row:
            c.execute("DELETE FROM kg_observations WHERE entity_id=?", (row["id"],))
            c.execute("DELETE FROM kg_entities WHERE id=?", (row["id"],))
        c.execute("DELETE FROM kg_relations WHERE src=? COLLATE NOCASE "
                  "OR dst=? COLLATE NOCASE", (name, name))


# ── reads ───────────────────────────────────────────────────────────────────

def get_graph() -> dict:
    with _conn() as c:
        ents = c.execute("SELECT * FROM kg_entities ORDER BY updated_at DESC").fetchall()
        obs = c.execute("SELECT * FROM kg_observations ORDER BY id").fetchall()
        rels = c.execute("SELECT * FROM kg_relations ORDER BY id").fetchall()
    obs_by = {}
    for o in obs:
        obs_by.setdefault(o["entity_id"], []).append(o["content"])
    entities = [{"id": e["id"], "name": e["name"], "type": e["type"],
                 "observations": obs_by.get(e["id"], [])} for e in ents]
    relations = [{"src": r["src"], "rel": r["rel"], "dst": r["dst"]} for r in rels]
    return {"entities": entities, "relations": relations}


def stats() -> tuple:
    with _conn() as c:
        e = c.execute("SELECT COUNT(*) FROM kg_entities").fetchone()[0]
        r = c.execute("SELECT COUNT(*) FROM kg_relations").fetchone()[0]
    return e, r


def graph_for_prompt(max_chars: int = 1400) -> str:
    g = get_graph()
    if not g["entities"]:
        return ""
    lines = ["--- KNOWLEDGE GRAPH (structured memory about the user's world) ---"]
    for e in g["entities"][:30]:
        obs = "; ".join(e["observations"][:3])
        line = f"- {e['name']} [{e['type']}]" + (f": {obs}" if obs else "")
        lines.append(line[:180])
    rels = g["relations"][:25]
    if rels:
        lines.append("Relations:")
        for r in rels:
            lines.append(f"- {r['src']} —{r['rel']}→ {r['dst']}")
    text = "\n".join(lines)
    return text[:max_chars]


def search(query: str, limit: int = 8) -> list:
    """Entities most relevant to a query (name + observation term overlap)."""
    terms = [t for t in re.findall(r'\w+', (query or "").lower()) if len(t) > 2]
    if not terms:
        return []
    scored = []
    for e in get_graph()["entities"]:
        hay = (e["name"] + " " + " ".join(e["observations"])).lower()
        score = sum(hay.count(t) for t in terms)
        if any(t in e["name"].lower() for t in terms):
            score += 3
        if score:
            scored.append((score, e))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:limit]]


def relevant_for_prompt(message: str, max_chars: int = 900) -> str:
    """Focused memory block: only entities relevant to the current message."""
    ents = search(message, 8)
    if not ents:
        return ""
    names = {e["name"] for e in ents}
    lines = ["--- RELEVANT MEMORY (from the knowledge graph) ---"]
    for e in ents:
        obs = "; ".join(e["observations"][:3])
        lines.append((f"- {e['name']} [{e['type']}]" + (f": {obs}" if obs else ""))[:180])
    rels = [r for r in get_graph()["relations"]
            if r["src"] in names or r["dst"] in names]
    for r in rels[:12]:
        lines.append(f"- {r['src']} —{r['rel']}→ {r['dst']}")
    return "\n".join(lines)[:max_chars]


def remember(arg: str) -> str:
    """[REMEMBER: entity | fact]  or  [REMEMBER: A | relation | B]."""
    parts = [p.strip() for p in (arg or "").split("|")]
    if len(parts) >= 3 and all(parts[:3]):
        add_relation(parts[0], parts[1], parts[2])
        return f"🧠 Linked: {parts[0]} —{parts[1]}→ {parts[2]}"
    if len(parts) == 2 and parts[0] and parts[1]:
        add_observation(parts[0], parts[1])
        return f"🧠 Remembered about {parts[0]}: {parts[1]}"
    return "REMEMBER needs [REMEMBER: entity | fact] or [REMEMBER: A | relation | B]"


# ── automatic extraction from conversations ─────────────────────────────────

_EXTRACT_PROMPT = (
    "Extract durable knowledge about the user's world from this exchange. "
    "Return ONLY compact JSON:\n"
    '{"entities":[{"name":"...","type":"person|project|device|place|organization|preference|event|concept|skill","observation":"short fact"}],'
    '"relations":[{"src":"entity","rel":"short verb phrase","dst":"entity"}]}\n'
    "Rules: only real, lasting facts (not small talk). Names are canonical "
    "(e.g. 'Hritick', 'Aria project', 'RTX 4060'). Empty arrays if nothing. "
    "No prose, JSON only."
)


def _extract_sync(user_message: str, assistant_reply: str):
    try:
        import requests
        model = cfg.get("model_fast") or cfg.get("ollama_model")
        payload = {
            "model": model, "stream": False, "format": "json",
            "options": {"temperature": 0.1, "num_ctx": 4096},
            "messages": [
                {"role": "system", "content": _EXTRACT_PROMPT},
                {"role": "user", "content":
                 f"User: {user_message}\nAssistant: {assistant_reply}"},
            ],
        }
        r = requests.post(f"{cfg.get('ollama_base_url')}/api/chat",
                          json=payload, timeout=60)
        r.raise_for_status()
        raw = r.json().get("message", {}).get("content", "")
        data = _safe_json(raw)
        if not data:
            return
        for e in data.get("entities", [])[:12]:
            name = str(e.get("name", "")).strip()
            if name:
                add_observation(name, str(e.get("observation", "")).strip(),
                                str(e.get("type", "concept")))
        for rel in data.get("relations", [])[:12]:
            add_relation(str(rel.get("src", "")), str(rel.get("rel", "")),
                         str(rel.get("dst", "")))
        e, rc = stats()
        log.info(f"KG updated → {e} entities, {rc} relations")
    except Exception as ex:
        log.warning(f"KG extract failed: {ex}")


def _safe_json(text: str):
    text = (text or "").strip()
    m = re.search(r'\{.*\}', text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def extract_async(user_message: str, assistant_reply: str):
    if not (user_message and assistant_reply):
        return
    threading.Thread(target=_extract_sync,
                     args=(user_message, assistant_reply), daemon=True).start()
