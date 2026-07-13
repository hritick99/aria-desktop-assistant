"""
Aider integration — reliable multi-file code editing on a git repo.

Aria shells out to the `aider` CLI (pip install aider-chat) in one-shot
mode: it applies an instruction to a target repo, auto-commits via git,
and we return a summary + the resulting diff stat. Aider uses whichever
model Aria is already configured for (Claude preferred for code quality).

Everything degrades gracefully: if Aider isn't installed, the tool tells
the user how to install it instead of crashing.
"""

import os
import subprocess
import sys

import config as cfg
from core.logger import get_logger

log = get_logger("aider")

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _python() -> str:
    return sys.executable or "python"


def available() -> bool:
    """True if the aider CLI is importable/runnable."""
    try:
        r = subprocess.run([_python(), "-m", "aider", "--version"],
                           capture_output=True, text=True, timeout=25,
                           creationflags=_CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def _model_and_env():
    """Map Aria's configured provider to an aider/litellm model + env vars.
    Claude is preferred for code; then a custom OpenAI-compatible provider;
    then Groq; finally local Ollama."""
    env = dict(os.environ)
    override = (cfg.get("aider_model") or "").strip()

    if cfg.get("claude_api_key"):
        env["ANTHROPIC_API_KEY"] = cfg.get("claude_api_key")
        return override or f"anthropic/{cfg.get('claude_model')}", env

    for c in (cfg.get("custom_llms") or []):
        if c.get("api_key") and c.get("base_url") and c.get("model"):
            env["OPENAI_API_KEY"] = c["api_key"]
            env["OPENAI_API_BASE"] = c["base_url"].rstrip("/")
            return override or f"openai/{c['model']}", env

    if cfg.get("groq_api_key"):
        env["GROQ_API_KEY"] = cfg.get("groq_api_key")
        return override or f"groq/{cfg.get('groq_model')}", env

    env["OLLAMA_API_BASE"] = cfg.get("ollama_base_url") or "http://localhost:11434"
    return override or f"ollama/{cfg.get('ollama_model')}", env


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, creationflags=_CREATE_NO_WINDOW)


def _ensure_git(repo):
    if not os.path.isdir(os.path.join(repo, ".git")):
        _git(repo, "init")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "aria: snapshot before Aider", "--allow-empty")


def run_aider(arg: str, timeout: int = 600) -> str:
    """[AIDER: repo_path | instruction] — apply a code change to a repo."""
    parts = (arg or "").split("|", 1)
    if len(parts) < 2 or not parts[1].strip():
        return "AIDER needs: [AIDER: /path/to/repo | what to change]"
    repo = os.path.expanduser(parts[0].strip().strip('"\''))
    instruction = parts[1].strip()

    if not os.path.isdir(repo):
        return f"Folder not found: {repo}"
    if not available():
        return ("Aider isn't installed yet. Install it once with:\n"
                "    pip install aider-chat\n"
                "Then ask me again.")

    _ensure_git(repo)
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    model, env = _model_and_env()
    cmd = [_python(), "-m", "aider",
           "--model", model,
           "--yes-always", "--no-stream", "--no-pretty",
           "--no-check-update", "--no-auto-lint",
           "--message", instruction]
    log.info(f"Aider ({model}) in {repo}: {instruction[:80]}")
    try:
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True,
                           timeout=timeout, env=env,
                           creationflags=_CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return f"Aider timed out after {timeout}s in {repo}."
    except Exception as e:
        return f"Aider failed to launch: {e}"

    tail = (r.stdout or "").strip()[-1200:]
    head_after = _git(repo, "rev-parse", "HEAD").stdout.strip()
    if head_after and head_after != head_before:
        stat = _git(repo, "diff", "--stat", f"{head_before}", head_after).stdout.strip()
        return (f"✓ Aider ({model}) edited the repo and committed the change.\n\n"
                f"Files changed:\n{stat or '(see log)'}\n\n"
                f"Aider log:\n{tail}")
    err = (r.stderr or "").strip()[-600:]
    return (f"Aider ran ({model}) but made no committed change.\n\n"
            f"Output:\n{tail}\n{('Errors: ' + err) if err else ''}")
