"""
Destructive-action confirmation gate.

When Aria has full control AND the safety net is on, a destructive action
(shell command that shuts down / formats / deletes / edits the registry,
or a write into a system folder) is not run immediately. It is parked
here, Aria asks the user "Run X? yes/no" in chat, and it only executes
after an explicit yes on the next message.
"""

import threading

_pending = None          # (kind, arg, human_description)
_lock = threading.Lock()

_YES = {"yes", "y", "yeah", "yep", "yup", "confirm", "confirmed", "do it",
        "go ahead", "proceed", "run it", "run", "sure", "affirmative"}
_NO = {"no", "n", "nope", "nah", "cancel", "stop", "abort", "nevermind",
       "never mind", "don't", "dont", "wait"}


def set_pending(kind: str, arg, human: str):
    global _pending
    with _lock:
        _pending = (kind, arg, human)


def has_pending() -> bool:
    with _lock:
        return _pending is not None


def pending_human() -> str:
    with _lock:
        return _pending[2] if _pending else ""


def clear():
    global _pending
    with _lock:
        _pending = None


def classify(text: str):
    """Return 'yes', 'no', or None for a user reply."""
    t = (text or "").strip().lower().rstrip("!. ")
    if t in _YES:
        return "yes"
    if t in _NO:
        return "no"
    words = t.split()
    # an explicit no anywhere wins (safer to cancel than to run)
    if any(w in _NO for w in words):
        return "no"
    if words and words[0] in _YES:
        return "yes"
    return None


def execute_pending() -> str:
    """Run the parked action (bypassing the guard) and clear it."""
    global _pending
    with _lock:
        p = _pending
        _pending = None
    if not p:
        return "Nothing was pending."
    kind, arg, _human = p
    try:
        if kind == "shell":
            from core.os_control import run_shell
            return run_shell(arg, confirmed=True)
        if kind == "write":
            from core.file_ops import write_file
            path, content = arg
            return write_file(path, content, confirmed=True)
        if kind == "email":
            from core.email_client import send_email
            to, subject, body = arg
            return send_email(to, subject, body)
    except Exception as e:
        return f"Action failed: {e}"
    return "Unknown pending action."
