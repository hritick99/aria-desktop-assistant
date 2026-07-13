<div align="center">

# Aria - AI Desktop Assistant

**A smart, warm, autonomous AI assistant that lives on your desktop.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://python.org)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-orange)](https://console.anthropic.com)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20AI-green)](https://ollama.com)
[![License](https://img.shields.io/badge/License-MIT-purple)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)]()

</div>

---

## What is Aria?

Aria is a fully autonomous AI desktop assistant built in Python. Unlike simple chatbots, Aria remembers you across sessions, controls your computer, connects to Gmail, GitHub, Google Calendar, runs locally with Ollama, and talks and listens using real voice.

---

## Features

### OS Control
- Open any app, type text, press key combos
- Set volume, kill processes, open URLs
- Run shell/PowerShell commands
- Screenshot and clipboard access

### Voice
- Speech-to-Text via faster-whisper (local, offline)
- Text-to-Speech via pyttsx3
- Wake word detection
- Voice activity detection

### Memory
- Persistent knowledge graph
- Remembers facts, preferences, context forever
- Proactive suggestions based on your habits

### Email (Gmail)
- Read, search, draft, send emails
- Filter by sender, subject, date, labels

### Google Calendar
- View today, tomorrow, this week
- Create new events

### GitHub
- List repos, PRs, issues, commits, notifications
- Create issues, PRs, branches, fork repos, merge PRs

### File Operations
- Read PDF, Word, Excel, txt, code files
- Write and find files
- RAG document indexing and semantic search

### Code and Dev
- Run Python in sandbox
- Multi-file code edits via Aider
- Delegate full project builds to Claude Code agent

### Reminders
- One-time, daily, weekday reminders
- List, snooze, complete, delete reminders

### AI Backends
- Claude (Anthropic) - cloud, powerful
- Ollama - 100% local and free

---

## Getting Started

### 1. Clone the repo
```
git clone https://github.com/hritick99/aria-desktop-assistant.git
cd aria-desktop-assistant
```

### 2. Create virtual environment
```
python -m venv venv
venv\Scripts\activate
```

### 3. Install dependencies
```
pip install -r requirements.txt
```

### 4. Run Aria
```
python main.py
```

---

## AI Backend Options

### Claude (Anthropic)
Get your API key at https://console.anthropic.com
Supports claude-3-5-sonnet, claude-3-opus, claude-3-haiku

### Ollama (100% Local and Free)
1. Install Ollama from https://ollama.com/download
2. Pull a model: ollama pull llama3
3. Start Ollama: ollama serve
4. Select Ollama in Aria settings

---

## Configuration

All settings are managed from the in-app Settings panel. No manual config file editing needed.

- AI Provider: Claude or Ollama
- Claude API Key and Model
- Ollama Model selection
- Plugin enable/disable toggles
- GitHub Personal Access Token
- Google OAuth for Gmail and Calendar
- MCP server configuration
- Voice settings (STT/TTS)
- Global hotkey configuration

---

## Built With

- Python 3.10+
- Anthropic Claude API
- Ollama
- faster-whisper (STT)
- pyttsx3 (TTS)
- tkinter (UI)
- Google API Python Client
- PyGithub
- DuckDuckGo Search
- Aider AI

---

## License

MIT License - see LICENSE file for details.

---

<div align="center">
Built with love by Hritick
</div>
