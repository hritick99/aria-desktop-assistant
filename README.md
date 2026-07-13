# Aria - AI Desktop Assistant

A smart, warm, autonomous AI assistant that lives on your desktop.

## Features

- Persistent Memory
- Full OS Control
- Web Search
- Voice Input/Output
- Email Integration
- Google Calendar
- GitHub Integration
- File Operations
- Clipboard Access
- Screenshot
- Reminders
- RAG Document Search
- Code Execution
- Aider / Claude Code Integration

## AI Backend - Claude OR Ollama

Aria is not locked to any single AI provider.

### Option A - Claude (Anthropic)
Get your key at: https://console.anthropic.com/

### Option B - Ollama (100% Local & Free)
1. Install Ollama: https://ollama.com/download
2. Pull a model: ollama pull llama3
3. Start Ollama: ollama serve
4. Select Ollama in Aria settings panel

## Prerequisites

- Python 3.10+
- Git
- Anthropic API key OR Ollama installed

## Getting Started

### 1. Clone
```bash
git clone https://github.com/hritick99/aria-desktop-assistant.git
cd aria-desktop-assistant
```n
### 2. Virtual Environment
```bash
python -m venv venv
venv\Scripts\activate
```n
### 3. Install Dependencies
```bash
pip install -r requirements.txt
```n
### 4. Run
```bash
python main.py
```n
## In-App Configuration

Once Aria is running, click Settings to configure:

### Model Settings
- AI Provider: Claude or Ollama
- Claude API Key
- Claude Model (claude-3-5-sonnet, claude-3-haiku, etc.)
- Ollama Model (llama3, mistral, gemma2, phi3, deepseek-r1, etc.)

### Plugins
- Gmail
- Google Calendar
- GitHub
- Web Search
- RAG Document Search
- Code Execution

### MCP Configuration
Aria supports MCP (Model Context Protocol) servers.
Add custom MCP servers from the settings panel with name, command, and args.

## License

MIT License - feel free to use, modify and distribute.
