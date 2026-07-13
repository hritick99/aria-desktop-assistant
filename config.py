"""
Config — JSON-backed, editable at runtime via Settings panel.
All defaults live here; user overrides saved to ~/.desktop_assistant/config.json
"""

import os
import json

_CONFIG_DIR  = os.path.join(os.path.expanduser("~"), ".desktop_assistant")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.json")

DEFAULTS = {
    "ollama_base_url":   "http://localhost:11434",
    "ollama_model":      "qwen2.5:3b",
    "model_vision":      "llava:7b",
    "model_code":        "deepseek-coder:6.7b",
    "model_reasoning":   "qwen2.5:7b",
    "model_fast":        "qwen2.5:3b",
    "assistant_name":    "Aria",
    "user_name":         "Hritick",
    "window_width":      420,
    "window_height":     580,
    "collapsed_size":    56,
    "window_x":          80,
    "window_y":          80,
    "opacity":           0.96,
    "hotkey":            "<alt>+<space>",
    "tts_enabled":       True,
    "tts_rate":          165,
    "tts_volume":        0.9,
    "tts_voice_idx":     0,
    "context_window":    20,
    "max_facts":         40,
    "episodic_days":     5,
    "whisper_model":     "base",
    "reminder_check_interval": 30,
    "wake_word_enabled": False,
    "wake_word":         "hey aria",
    "wake_threshold":    0.5,
    "vad_enabled":       False,
    "rag_index_paths":   [],
    "github_token":      "",
    "github_username":   "",
    "log_level":         "INFO",

    # ── Cloud LLM providers (keys entered via Settings UI) ──
    "llm_backend":       "auto",          # auto | ollama | groq | claude
    "groq_api_key":      "",
    "groq_base_url":     "https://api.groq.com/openai/v1",
    "groq_model":        "llama-3.3-70b-versatile",
    "claude_api_key":    "",
    "claude_base_url":   "https://api.anthropic.com/v1",
    "claude_model":      "claude-sonnet-4-6",
    "claude_max_tokens": 1500,

    # Any OpenAI-compatible cloud LLM (OpenAI, OpenRouter, Mistral, DeepSeek…)
    # Each entry: {"name": ..., "base_url": ..., "api_key": ..., "model": ...}
    "custom_llms":       [],

    # MCP connectors (like Claude desktop) — spawned as stdio subprocesses.
    # Each entry: {"name": ..., "command": ..., "enabled": true}
    "mcp_servers":       [],

    # Phone push notifications via ntfy.sh — install the ntfy app and
    # subscribe to the topic. Topic is auto-generated on first enable.
    "ntfy_enabled":      False,
    "ntfy_server":       "https://ntfy.sh",
    "ntfy_topic":        "",

    # Full computer control: disables the shell command blocklist, the
    # system-directory write guard, and the Python sandbox restrictions.
    "full_control":      False,
    # Safety net for full control: destructive actions (shutdown/format/
    # delete/registry/system-writes) ask "yes/no" in chat before running.
    "confirm_destructive": True,

    # Aider code-editing integration. Blank = auto-pick a litellm model
    # from the configured provider keys (Claude preferred for code).
    "aider_model":       "",

    # Which code-editing backend [CODEEDIT] uses:
    #   'aider'       → Aider CLI (API key, pay per token)
    #   'claude_code' → Claude Code CLI (your Claude Pro subscription)
    "code_backend":      "aider",
    # Last project folder used in the Code Workspace panel.
    "code_project_dir":  "",

    # Email (IMAP, read-only). For Gmail use an App Password, not your login
    # password: https://myaccount.google.com/apppasswords
    "email_address":     "",
    "email_app_password": "",
    "email_imap_host":   "imap.gmail.com",
    "email_smtp_host":   "smtp.gmail.com",
}


def _load() -> dict:
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE) as f:
                user = json.load(f)
            return {**DEFAULTS, **user}
        except Exception:
            pass
    return dict(DEFAULTS)


def _save(cfg: dict):
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    with open(_CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


_cfg = _load()


def get(key: str):
    return _cfg.get(key, DEFAULTS.get(key))


def set(key: str, value):
    _cfg[key] = value
    _save(_cfg)


def get_all() -> dict:
    return dict(_cfg)


def reset():
    global _cfg
    _cfg = dict(DEFAULTS)
    _save(_cfg)


DB_PATH  = os.path.join(_CONFIG_DIR, "memory.db")
LOG_PATH = os.path.join(_CONFIG_DIR, "aria.log")
