<div align="center">

# Aria — Local Desktop AI Assistant

**A private, always-available AI assistant that lives on your Windows desktop.**

[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)](https://python.org)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-orange)](https://www.anthropic.com/claude-code)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20AI-green)](https://ollama.com)
[![License](https://img.shields.io/badge/License-MIT-purple)](LICENSE)

</div>

Aria runs as a floating overlay, remembers you across sessions, controls your PC,
edits code, reads your email, browses the web, and can route her "brain" between
local models (Ollama) and the cloud — including your **Claude Pro subscription**
(no API tokens). Built with Python + CustomTkinter, backed by SQLite, with a
plugin / MCP-connector architecture modelled on Claude Desktop.

---

## Highlights

- **Floating overlay UI** — warm, minimal, Claude-style. Collapses to a small
  animated robot; drag anywhere; global hotkey (`Alt+Space`), tray icon, wake word.
- **Multiple brains, automatic failover** — Groq → OpenAI-compatible → Claude →
  local Ollama, with per-provider cooldown on rate-limits. Or pin one backend.
- **Claude Pro subscription mode** — route chat through the Claude Code CLI so
  answers use your subscription instead of paid API tokens.
- **Vision** — reads your screen and images via a local vision model (llava /
  qwen2.5vl); screenshots render inline in the chat.
- **Knowledge graph memory** — a self-building graph of entities, observations,
  and relations, with a visual node/edge viewer. Grows from conversation and on
  command (`remember …`), and feeds relevant facts back into every answer.
- **Full computer control** — terminal (PowerShell), file read/write/find, app
  control, volume, processes — with a destructive-action confirmation gate.
- **Code Workspace** — build, edit and run projects with **Aider** or **Claude
  Code**; file list, live run output, git-committed edits.
- **Autonomous agent** — delegate whole multi-step tasks to the Claude Code agent.
- **MCP connectors** — one-click catalog: filesystem, memory, web (Puppeteer),
  sequential-thinking, GitHub — the same plugin ecosystem as Claude Desktop.
- **Email** — read and filter your inbox over IMAP (full Gmail search syntax),
  send with a confirmation step.
- **Reminders** — natural-language scheduling that survives restarts, delivers
  missed ones on next launch, pushes to your phone (ntfy), Done/Snooze actions.
- **Session history** — browse and reopen past conversations; start fresh chats.

---

## Features in detail

### Brains & routing (`core/llm_providers.py`)
- Backends: `auto`, `ollama`, `groq`, `claude`, `claude_code`, and any custom
  OpenAI-compatible provider (OpenAI, OpenRouter, Mistral, DeepSeek…).
- Automatic failover chain that ends at local Ollama so Aria never hard-fails;
  a provider that 429s is put on a short cooldown.
- Per-provider **Test** buttons in Settings; local model routing by intent
  (fast / reasoning / code / vision).

### Memory (`core/memory.py`, `core/knowledge_graph.py`, `core/world_model.py`)
- Flat semantic facts + episodic conversation logs (SQLite).
- **Knowledge graph**: typed entities, observations, and relations; automatic
  background extraction; `[REMEMBER: entity | fact]` / `[REMEMBER: A | rel | B]`;
  relevance retrieval into the prompt; visual graph viewer (🕸).

### Tools the model can call
`[SEARCH]` web · `[CODE]` sandboxed Python · `[SHELL]` PowerShell · `[FILE]` read ·
`[WRITE]` create files/docx · `[FIND]` find files · `[OS]` open/type/volume/kill/url ·
`[CODEEDIT]` Aider/Claude Code · `[DELEGATE]` autonomous agent · `[EMAIL]`
read/filter/send · `[RAG]` local docs · `[REMINDERS]` manage · `[REMEMBER]`
knowledge graph · `[MCP: server.tool]` connectors.

### Safety
- **Full computer control** toggle (off by default) gates the terminal blocklist,
  system-folder writes, and the Python sandbox.
- **Confirmation gate** — destructive commands (shutdown/format/registry/deletes),
  system-folder writes, and email sends ask "yes/no" in chat first.

### Code (`core/aider_integration.py`, `core/claude_code_integration.py`, `ui/code_panel.py`)
- **Code Workspace** panel: pick a repo, choose engine, describe a change, Build;
  file list with changed files highlighted, Run button with live output.
- **Aider** (API key) or **Claude Code** (subscription) backends.
- **Delegate** a full task to the Claude Code agent (builds real projects).

### Connectors (`core/mcp_client.py`)
- MCP stdio client; one-click catalog in Settings; per-connector env (tokens);
  filesystem + memory wired by default.

### Email (`core/email_client.py`)
- IMAP read + Gmail search-syntax filtering (read-only mailbox); SMTP send with
  confirmation. Uses a Gmail **App Password** (no Google Cloud project needed).

### Reminders (`core/reminders.py`)
- Natural-language scheduling, persistent across restarts, missed-reminder
  catch-up, phone push via ntfy, Done / +10 min snooze, chat management.

---

## Requirements

- **Windows 10/11**, Python 3.12
- **[Ollama](https://ollama.com)** running locally with at least:
  `ollama pull qwen2.5:3b` (chat) and `ollama pull nomic-embed-text` (RAG).
  Optional: `qwen2.5:7b` (reasoning), `llava:7b` (vision).
- Optional cloud brains: Groq / OpenAI / Anthropic keys, or
  **[Claude Code](https://www.anthropic.com/claude-code)** logged in with a
  Claude subscription.
- Optional for connectors / Claude Code: **Node.js**.

## Setup

```bash
pip install -r requirements.txt
python main.py
```

Then open **⚙ Settings** to add API keys, choose a backend, connect email, enable
connectors, and pick your models. Most features are optional and light up only
once configured.

## Configuration

All settings live in `~/.desktop_assistant/config.json` (created on first run) and
are editable from the Settings panel. Nothing sensitive is stored in this repo.

---

<div align="center">
<em>Personal project. Runs entirely on your machine; your data stays local except
for calls to any cloud LLM providers you explicitly configure.</em>
</div>
