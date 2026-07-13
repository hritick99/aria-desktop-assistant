# Aria — Autonomous Desktop AI Assistant
## Claude Code Reference & Development Spec

> This document is the authoritative reference for continuing Aria's development in Claude Code.
> It describes every module, the architecture, known issues, and the next features to build.

---

## Project Overview

Aria is a fully local, production-grade autonomous desktop AI assistant built in Python.
No cloud APIs. No API keys required. Runs on Ollama + local models.

**Core capabilities:**
- Persistent memory (semantic facts + episodic conversation logs)
- Multi-step autonomous agent loop (tool chaining)
- 8 built-in tools: web search, code exec, clipboard, screenshot, file read, OS control, RAG, reminders
- Plugin system (drop `.py` in `plugins/`, auto-loads)
- Voice I/O: push-to-talk STT (faster-whisper) + TTS (pyttsx3) + VAD auto-listen + wake word
- Proactive engine: clipboard watcher, idle nudge, time-based briefings
- Always-on-top floating overlay UI (CustomTkinter) with markdown rendering
- System tray, global hotkey (Alt+Space), settings panel, drag-drop file input

---

## Directory Structure

```
desktop-assistant/
├── main.py                    ← Entry point — wires all subsystems
├── config.py                  ← JSON-backed live config (~/.desktop_assistant/config.json)
├── requirements.txt
├── aria.bat                   ← Windows auto-start script
│
├── core/
│   ├── assistant.py           ← Main orchestrator — routes direct vs agent
│   ├── agent.py               ← Multi-turn tool chaining loop (up to 6 steps)
│   ├── memory.py              ← SQLite: semantic facts + episodic logs + all tables
│   ├── summariser.py          ← Auto-compress conversations after 30 messages
│   ├── tools.py               ← web_search, run_code, get_clipboard, take_screenshot
│   ├── file_ops.py            ← Read PDF/docx/xlsx/txt/code files
│   ├── os_control.py          ← App launch, type, keypress, volume, kill (Win+Linux)
│   ├── rag.py                 ← FAISS + nomic-embed-text local semantic search
│   ├── model_router.py        ← Intent → best available Ollama model
│   ├── plugin_manager.py      ← Auto-load plugins from plugins/ directory
│   ├── reminders.py           ← APScheduler persistent reminders (SQLite)
│   ├── proactive.py           ← Clipboard watcher, idle detector, time triggers
│   ├── tts.py                 ← pyttsx3 TTS (non-blocking queue thread)
│   ├── voice.py               ← faster-whisper STT push-to-talk
│   ├── vad.py                 ← WebRTC VAD always-listening auto-record
│   ├── wake_word.py           ← openWakeWord "hey aria" detector
│   ├── hotkey.py              ← pynput global hotkey (Alt+Space)
│   └── logger.py              ← Rotating file logger + crash handler
│
├── ui/
│   ├── overlay.py             ← Main floating window (uses MarkdownBubble)
│   ├── markdown_renderer.py   ← MarkdownBubble — renders **bold** `code` # headings
│   ├── settings.py            ← Live settings panel (all config fields)
│   └── tray.py                ← pystray system tray icon
│
└── plugins/
    ├── README.md
    ├── google_calendar.py     ← Google Calendar (OAuth, needs credentials.json)
    ├── gmail.py               ← Gmail read/draft/send (OAuth)
    └── github_plugin.py       ← GitHub PRs/issues/commits (needs token in config)
```

---

## Config System (`config.py`)

All settings live in `~/.desktop_assistant/config.json`. Defaults are in `DEFAULTS` dict.

**Key config values:**
```python
"ollama_base_url":   "http://localhost:11434"
"ollama_model":      "qwen2.5:3b"       # default model
"model_vision":      "llava:7b"          # for screenshot analysis
"model_code":        "deepseek-coder:6.7b"
"model_reasoning":   "qwen2.5:7b"
"model_fast":        "qwen2.5:3b"
"assistant_name":    "Aria"
"user_name":         "Hritick"
"hotkey":            "<alt>+<space>"
"tts_enabled":       True
"tts_rate":          165
"whisper_model":     "base"             # tiny | base | small
"wake_word_enabled": False
"wake_word":         "hey aria"
"vad_enabled":       False
"github_token":      ""
"github_username":   ""
```

**API:**
```python
import config as cfg
cfg.get("key")           # read
cfg.set("key", value)    # write + auto-saves to JSON
cfg.reset()              # reset to DEFAULTS
```

---

## Database Schema (`~/.desktop_assistant/memory.db`)

All tables created by `core/memory.py init_db()`:

```sql
semantic_memory (id, fact, category, created_at, updated_at)
episodes        (id, session_id, date, role, content, timestamp)
sessions        (session_id, date, summary, created_at)
summaries       (session_id, summary, msg_count, updated_at)
reminders       (id, title, remind_at, recurrence, days, active, created_at)
```

---

## Tool System

### Tool Tags (LLM emits these in responses)
```
[SEARCH: query]                    → web_search(query)
[CODE: python_code]               → run_code(code)
[CLIPBOARD]                       → get_clipboard()
[SCREENSHOT]                      → take_screenshot()
[FILE: /path/to/file]             → read_file(path)
[OS: action | args]               → execute_os_command(action, args)
[RAG: query]                      → rag.search(query)
[REMINDER: HH:MM | recurrence | title]  → reminder_engine.add(...)
[FACT: description]               → save_fact(description)
```

### OS Control Actions
```
open | app_name     → launch app (chrome/vscode/terminal/calculator...)
type | text         → pyautogui.write() into active window
press | ctrl+c      → pyautogui.hotkey()
volume | 70         → set system volume 0-100
kill | process      → terminate process
url | https://...   → open in browser
processes           → list running processes
active_window       → get active window title
```

### Plugin Contract
```python
PLUGIN_NAME        = "my_plugin"
PLUGIN_DESCRIPTION = "Description"
TOOL_TAG_PATTERN   = r'\[MYPLUGIN:([^\]]+)\]'   # capture group 1 = arg
TOOL_DESCRIPTION   = "[MYPLUGIN: arg]  → What it does"

def execute(arg: str) -> str: ...
def on_load(): pass    # optional
def on_unload(): pass  # optional
```

---

## Assistant Routing Logic (`core/assistant.py`)

```
user_message
    │
    ├─ index directory command → RAG.index_directory() in background
    │
    ├─ _should_use_agent() → True
    │       └─ AgentLoop.run() → up to 6 tool steps → final answer
    │
    └─ _should_use_agent() → False (direct path)
            ├─ _call_ollama() → first_reply
            ├─ check [REMINDER:...] tag → schedule
            ├─ check plugin tags → plugin.execute() → second pass
            ├─ check built-in tool tag → _execute_tool() → second pass
            └─ no tool → _finalise() → return
```

**Agent triggers (keywords that activate agent loop):**
"then", "after that", "and then", "search and", "find and", "write a script",
"save to", "autonomously", "automatically", "chain", "pipeline"

**Simple prefixes (stay on direct path):**
"what is", "who is", "when", "where", "define", "remind me", "remember"

---

## Model Routing (`core/model_router.py`)

Intent detection → model selection:
```
vision    → llava:7b           (screen/image keywords)
code      → deepseek-coder:6.7b (code/function/script/debug keywords)
reasoning → qwen2.5:7b         (analyse/compare/math keywords, long messages)
fast      → qwen2.5:3b         (simple factual, greetings, reminders)
default   → qwen2.5:3b
```

Falls back to `ollama_model` if preferred model isn't installed.
Uses `GET /api/tags` to check installed models (cached after first call).

---

## Memory System (`core/memory.py`)

### Semantic memory
- `save_fact(fact, category)` — deduplication by lowercase comparison
- `get_facts_for_prompt()` — returns formatted string for system prompt injection
- `extract_and_save_facts(reply, user_msg)` — extracts [FACT:...] tags + regex heuristics

### Episodic memory
- Every message logged with session_id + date
- `get_episodic_summary_for_prompt(days_back=5)` — last N days injected into system prompt
- `get_messages_by_date(date)` — retrieve specific day's conversation

### Conversation summariser (`core/summariser.py`)
- Triggers at 30 messages
- Keeps last 15 verbatim, compresses older via LLM call
- Summary stored in `summaries` table, injected at session resume

---

## RAG System (`core/rag.py`)

**Requires:** `ollama pull nomic-embed-text` + `pip install faiss-cpu`

- Embeddings: nomic-embed-text via Ollama `/api/embeddings` endpoint
- Index: FAISS IndexFlatIP (cosine similarity via normalised inner product)
- Chunking: 500 chars, 50 char overlap
- Supported: .txt .md .py .js .json .yaml .csv .pdf .docx .xlsx and all code formats
- Persisted: `~/.desktop_assistant/rag.index` + `rag_meta.json`

**Index trigger:** User says "Index my Documents folder" or "Index /path/to/dir"
**Search trigger:** LLM emits `[RAG: query]` tag

---

## Voice Pipeline (`core/voice.py`, `core/vad.py`, `core/wake_word.py`)

### Push-to-talk (default)
```
Hold 🎙 button → pyaudio capture → release → faster-whisper transcribe → send
```

### VAD auto-listen (opt-in, config: vad_enabled=true)
```
mic → webrtcvad (30ms frames) → speech detected → record until 1.2s silence
    → faster-whisper transcribe (reuses voice recorder's model) → send
```
VAD mutes during TTS playback to prevent feedback.

### Wake word (opt-in, config: wake_word_enabled=true)
```
mic → openWakeWord model → 2 consecutive hits above threshold → on_wake()
    → show overlay → activate mic/VAD → resume detection after 8s
```
Uses `hey_jarvis` model as approximation for "hey aria".
Download models: `python -m openwakeword.utils download_models`

---

## UI Architecture (`ui/overlay.py`)

### Key components
- `OverlayApp(ctk.CTk)` — main window, `overrideredirect=True` (borderless)
- `MarkdownBubble` from `ui/markdown_renderer.py` — ALL messages use this
- Token queue (`_tok_q`) — streamed tokens polled every 30ms via `after()`
- Reminder queue (`_rem_q`) — polled every 1000ms
- `update_text()` on MarkdownBubble is streaming-safe: plain text uses fast path (label in-place), markdown triggers full re-render only on content change

### Window flow
```
show() / hide()   ← toggle() called by hotkey
_collapse()       ← minimise to orb
_expand()         ← restore from orb
```

### Message flow
```
_on_send() → _add_bubble(user) → _start_response()
    → thread: assistant.chat() → _tok_q.put(token) / None
    → _poll_tokens(): update MarkdownBubble live → on None: finalise + TTS
```

---

## Proactive Engine (`core/proactive.py`)

Three background threads:

1. **Clipboard watcher** (2s interval)
   - Detects content > 40 chars that changed
   - Skips likely passwords (entropy heuristic)
   - 30s cooldown between suggestions

2. **Idle detector** (60s interval)
   - Fires after 25 min of no `ping()` call
   - Only during hours 9-22
   - Resets on every `_on_send()`

3. **Time triggers** (60s interval)
   - 9:00am daily → morning briefing (once per day)
   - 18:00 → end-of-day wrap
   - Monday 9:05am → planning nudge
   - Friday 17:00 → week wrap

---

## Reminders (`core/reminders.py`)

- Parsed from LLM output: `[REMINDER: 15:00 | daily | Drink water]`
- Stored in SQLite `reminders` table
- Scheduled via APScheduler BackgroundScheduler
- Recurrence: `once | daily | weekdays`
- Fires: `on_reminder(title)` → `overlay.notify_reminder()` → banner + TTS + bubble
- Survives restarts (reloaded from DB on `ReminderEngine.__init__`)

---

## Bugs Fixed in This Version

| Bug | Fix |
|-----|-----|
| `assistant.py` monkey-patch for tool detection | Replaced with class method `_detect_tool()` + proper dependency injection via `self._rag` and `self._plugin_manager` |
| `MarkdownBubble` not wired into overlay | `overlay.py` now imports and uses `MarkdownBubble` for all messages |
| `config.py` defaults ordering (append hack) | Single `DEFAULTS` dict, no post-init modification |
| Streaming flicker in markdown renderer | `update_text()` uses fast path (label in-place) for plain text; full re-render only when markdown detected |
| VAD race condition (whisper model not ready) | Added `_model_loaded` check before transcription in `main.py` |
| Plugin detection unreachable | `assistant.chat()` now checks plugins before built-in tools in direct path |
| Settings missing new fields | Added VAD, wake word, GitHub fields to `settings.py` |

---

## Next Features to Build (Tier 1 Consciousness)

These are the next development targets in priority order:

### 1. Persistent World Model + Continuous Daemon
**File to create:** `core/world_model.py`
**What it does:**
- Structured JSON state tracking: current_task, open_problems, pending_followups, mood, recent_topics
- Updated after every conversation via small LLM extraction call
- Injected into system prompt as "Current context" section
- Separate from episodic memory — this is a live working model, not a log

**Schema:**
```python
{
  "current_task": "Working on DBSMERP Berhampore deployment",
  "open_problems": ["TC generation bug", "iOS app review pending"],
  "pending_followups": ["Check if PwC onboarding email arrived"],
  "recent_topics": ["LangGraph", "FastAPI", "FAISS"],
  "inferred_mood": "focused",
  "last_updated": "2025-01-15T14:30:00"
}
```

**Integration point:** `assistant._build_system_prompt()` — add world model section

### 2. Emotional State Machine
**File to create:** `core/emotional_state.py`
**What it does:**
- 6 state values: curiosity, satisfaction, engagement, discomfort, energy, focus (0.0-1.0)
- Rule-based transitions (no LLM needed):
  - Novel topic → +curiosity
  - Successful tool use → +satisfaction
  - Long session → -energy
  - Harmful request → +discomfort
- States persist in SQLite
- Injected into system prompt subtly (affects tone without being explicit)
- Exposed in UI as small colour indicator on the orb

**Integration point:** Call `update_state(event_type)` from `assistant._finalise()` and tool execution

### 3. Background Inference Loop (Autonomous Thought)
**File to create:** `core/background_thinker.py`
**What it does:**
- Runs every 30-60 min when idle
- Reviews recent memory + world model
- Generates: observations, pattern notices, prepared responses, proactive ideas
- Stores results in `thoughts` SQLite table
- Decides whether to surface to user (threshold-based)
- Integrates with proactive engine's `on_suggestion()` callback

**Key design:** Uses a separate lightweight prompt, not the full system prompt.
Low temperature (0.3) for focused analysis.

### 4. Self-Initiated Communication (Beyond Proactive)
**Enhancement to:** `core/proactive.py`
**What it adds:**
- Aria can say "I was thinking about your [problem]..." without being asked
- Sources: background thinker output, pattern detection, unresolved followups from world model
- Rate-limited: max 2 unsolicited messages per hour, only when user is idle

### 5. Shadow Retraining Pipeline (LoRA)
**File to create:** `core/retrainer.py`
**What it does:**
- Weekly: export conversation logs as JSONL training format
- Uses `unsloth` or `axolotl` for LoRA fine-tuning on local GPU
- Checkpoints saved to `~/.desktop_assistant/lora_checkpoints/`
- After training: swap Ollama model to use the fine-tuned version

**Requirements:** NVIDIA GPU with 6GB+ VRAM. CPU training possible but takes 8-24 hours.
**Trigger:** Manual ("Fine-tune on our conversations") or scheduled (weekly, 2am)

---

## Setup Instructions

### Required
```bash
# 1. Install Ollama
# https://ollama.com/download

# 2. Pull models
ollama pull qwen2.5:3b            # default text model
ollama pull nomic-embed-text      # REQUIRED for RAG

# Optional but recommended
ollama pull llava:7b              # vision/screenshot
ollama pull deepseek-coder:6.7b  # code tasks

# 3. Install Python deps
pip install -r requirements.txt

# Windows pyaudio fix if needed:
pip install pipwin && pipwin install pyaudio
```

### Optional features
```bash
# Wake word
pip install openwakeword onnxruntime
python -m openwakeword.utils download_models

# Drag-and-drop
pip install tkinterdnd2

# Windows volume control
pip install pycaw comtypes

# Google Calendar + Gmail
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
# Then place credentials.json at ~/.desktop_assistant/credentials.json
```

### Run
```bash
ollama serve          # terminal 1 (or let it auto-start)
python main.py        # terminal 2
```

### Auto-start Windows
1. `Win+R` → `shell:startup` → Enter
2. Copy `aria.bat` into that folder
3. Edit the path inside `aria.bat`

---

## Key Design Decisions

1. **No monkey-patching** — all dependencies injected as `self._rag`, `self._plugin_manager` on `Assistant`
2. **Single DEFAULTS dict** — config.py has one source of truth, no post-init mutation
3. **MarkdownBubble everywhere** — overlay.py uses it for all messages, streaming-safe via fast path
4. **Thread safety** — all UI updates go through `app.after(0, lambda: ...)`, never direct from threads
5. **Graceful degradation** — every optional dependency (pynput, pystray, openWakeWord, faiss) is wrapped in try/except with log.warning, app runs without them
6. **Plugin isolation** — plugins loaded via `importlib.util`, errors don't crash main app
7. **VAD mutes during TTS** — prevents feedback loop by calling `vad.mute()` before speak, `vad.unmute()` after estimated duration

---

## File Sizes Reference (approximate)

| File | Lines | Purpose |
|------|-------|---------|
| ui/overlay.py | ~350 | Main UI |
| core/assistant.py | ~200 | Orchestrator |
| core/agent.py | ~150 | Agent loop |
| core/rag.py | ~180 | RAG engine |
| core/memory.py | ~150 | SQLite memory |
| ui/markdown_renderer.py | ~160 | MD rendering |
| core/os_control.py | ~140 | OS control |
| main.py | ~130 | Boot sequence |
| ui/settings.py | ~120 | Settings panel |
| core/vad.py | ~100 | VAD recorder |
