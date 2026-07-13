"""
Unified code-editing entry point. Routes [CODEEDIT: repo | instruction] to
whichever backend is selected in Settings:

  - 'aider'       → Aider CLI, uses your API key (config code_backend).
  - 'claude_code' → Claude Code CLI, uses your Claude Pro subscription.

If the chosen backend isn't ready, we say how to enable it (and, for
Claude Code, fall back to Aider when Aider is available so the edit still
happens).
"""

import config as cfg
from core.logger import get_logger

log = get_logger("code_edit")


def backend() -> str:
    b = (cfg.get("code_backend") or "aider").lower()
    return b if b in ("aider", "claude_code") else "aider"


def backend_label() -> str:
    return "Claude Code" if backend() == "claude_code" else "Aider"


def run(arg: str) -> str:
    if backend() == "claude_code":
        from core.claude_code_integration import run_claude_code, available
        if available():
            return run_claude_code(arg)
        # Not ready → prefer Aider if it's installed, else explain setup.
        from core.aider_integration import available as aider_ok, run_aider
        if aider_ok():
            log.info("Claude Code not ready; falling back to Aider")
            return "(Claude Code not set up — used Aider instead)\n\n" + run_aider(arg)
        from core.claude_code_integration import _SETUP_HELP
        return _SETUP_HELP
    from core.aider_integration import run_aider
    return run_aider(arg)
