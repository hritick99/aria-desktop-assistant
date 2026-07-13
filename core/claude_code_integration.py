"""
Claude Code integration — edit code using your Claude Pro/Max subscription
instead of paying per-token on the API.

Aria shells out to the `claude` CLI (Claude Code) in headless mode
(`claude -p "instruction"`) inside a target repo. When you are logged in
with a Claude subscription, this uses that subscription's included usage,
NOT your API key — so we deliberately strip ANTHROPIC_API_KEY from the
environment before calling it.

Setup (one time, by the user):
  1. Install Node.js         (https://nodejs.org)
  2. npm install -g @anthropic-ai/claude-code
  3. Run `claude` once and log in with your Claude account.
"""

import os
import re
import shutil
import subprocess
import tempfile

from core.logger import get_logger

log = get_logger("claude_code")

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

_SETUP_HELP = (
    "Claude Code isn't set up yet. To edit code with your Claude Pro "
    "subscription (no API tokens):\n"
    "  1. Install Node.js  → https://nodejs.org\n"
    "  2. npm install -g @anthropic-ai/claude-code\n"
    "  3. Run `claude` once in a terminal and log in with your Claude account.\n"
    "Then pick 'Claude Code' as the code backend in Settings."
)


def _exe():
    # PATH first (works once the shell has picked up the npm global dir)
    for name in ("claude", "claude.cmd", "claude.exe"):
        p = shutil.which(name)
        if p:
            return p
    # Fallbacks: common npm-global locations, incl. winget's Node install.
    import glob
    candidates = []
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        candidates.append(os.path.join(appdata, "npm", "claude.cmd"))
    la = os.environ.get("LOCALAPPDATA", "")
    if la:
        candidates += glob.glob(os.path.join(
            la, "Microsoft", "WinGet", "Packages",
            "OpenJS.NodeJS*", "node-*", "claude.cmd"))
        candidates.append(os.path.join(la, "Programs", "nodejs", "claude.cmd"))
    candidates.append(r"C:\Program Files\nodejs\claude.cmd")
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def available() -> bool:
    exe = _exe()
    if not exe:
        return False
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=25, creationflags=_CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def _sub_env():
    """Env without ANTHROPIC_API_KEY so Claude Code uses the subscription."""
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def complete_text(system, messages, on_token=None, timeout=240) -> str:
    """Use Claude Code as a plain chat LLM via your Pro subscription.

    The whole conversation is piped on stdin; Aria's system prompt is added
    with --append-system-prompt. Runs in 'plan' permission mode so Claude
    Code can't touch files — it just answers as text (Aria still parses any
    tool tags itself). Raises on failure so the provider layer can fall back.
    """
    exe = _exe()
    if not exe:
        raise RuntimeError("Claude Code CLI not found")

    parts = []
    for m in messages:
        if not m.get("content"):
            continue
        who = "User" if m["role"] == "user" else "Assistant"
        parts.append(f"{who}: {m['content']}")
    prompt = "\n\n".join(parts) or "Hello"

    workdir = os.path.join(tempfile.gettempdir(), "aria_claude_code")
    os.makedirs(workdir, exist_ok=True)
    # Block Claude Code's own agentic tools so it behaves as a plain text LLM
    # (Aria parses any [SHELL:]/[SEARCH:] tags itself). In -p mode there's no
    # TTY, so a blocked tool can't hang on a permission prompt.
    cmd = [exe, "-p",
           "--append-system-prompt", system,
           "--output-format", "text",
           "--disallowedTools",
           "Bash Edit Write Read WebFetch WebSearch Glob Grep Task "
           "NotebookEdit TodoWrite MultiEdit"]
    try:
        r = subprocess.run(cmd, cwd=workdir, input=prompt, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout, env=_sub_env(),
                           creationflags=_CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Claude Code timed out after {timeout}s")

    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if not out:
        low = (err + out).lower()
        if "logged in" in low or "login" in low or "authenticat" in low:
            raise RuntimeError("Claude Code not logged in — run `claude` and sign "
                               "in with your Claude Pro account.")
        raise RuntimeError(err[:200] or "Claude Code returned no output")

    if on_token:                       # simulate streaming for the UI
        for chunk in re.findall(r'\S+\s*', out):
            on_token(chunk)
    return out


def run_agent(task: str, workdir: str = None, timeout: int = 1800) -> str:
    """Full autonomous agent: hand a complex, multi-step task to Claude Code's
    real agent (creates/edits files, iterates) via your subscription. Runs in
    a working directory so it can build actual projects. acceptEdits mode
    auto-applies file changes; no interactive prompts (headless)."""
    task = (task or "").strip()
    if not task:
        return "Nothing to delegate."
    exe = _exe()
    if not exe:
        return _SETUP_HELP
    import config as cfg
    workdir = (workdir or cfg.get("code_project_dir") or
               os.path.join(os.path.expanduser("~"), "AriaWorkspace"))
    os.makedirs(workdir, exist_ok=True)
    cmd = [exe, "-p", task, "--permission-mode", "acceptEdits",
           "--output-format", "text"]
    log.info(f"Delegating to Claude Code agent in {workdir}: {task[:80]}")
    try:
        r = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=_sub_env(),
                           creationflags=_CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return f"Agent still working after {timeout}s — stopped. Check {workdir}."
    except Exception as e:
        return f"Agent failed to launch: {e}"
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    low = (err + out).lower()
    if "not logged in" in low or "please run /login" in low:
        return ("Claude Code isn't logged in. Run `claude` in a terminal and sign "
                "in with your Claude account, then try again.")
    return (f"✓ Agent finished in {workdir}\n\n{out[-2500:] or '(done)'}"
            + (f"\n\n[stderr] {err[-300:]}" if err and not out else ""))


def run_claude_code(arg: str, timeout: int = 900) -> str:
    """[CODEEDIT: repo | instruction] via Claude Code + your subscription."""
    parts = (arg or "").split("|", 1)
    if len(parts) < 2 or not parts[1].strip():
        return "Needs: [CODEEDIT: /path/to/repo | what to change]"
    repo = os.path.expanduser(parts[0].strip().strip('"\''))
    instruction = parts[1].strip()

    if not os.path.isdir(repo):
        return f"Folder not found: {repo}"
    exe = _exe()
    if not exe:
        return _SETUP_HELP

    cmd = [exe, "-p", instruction, "--permission-mode", "acceptEdits"]
    log.info(f"Claude Code in {repo}: {instruction[:80]}")
    try:
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=_sub_env(),
                           creationflags=_CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return f"Claude Code timed out after {timeout}s in {repo}."
    except Exception as e:
        return f"Claude Code failed to launch: {e}"

    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    low = (err + out).lower()
    if ("not logged in" in low or "please run /login" in low or
            ("auth" in low and "error" in low)):
        return ("Claude Code is installed but not logged in. Run `claude` in a "
                "terminal, log in with your Claude Pro account, then try again.")
    if r.returncode != 0 and not out:
        return f"Claude Code error:\n{err[:600] or '(no output)'}"
    return (f"✓ Claude Code (your subscription) worked in {repo}.\n\n"
            f"{out[-1500:] or '(done — see the repo for changes)'}")
