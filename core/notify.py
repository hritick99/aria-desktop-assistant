"""
Phone push notifications via ntfy (https://ntfy.sh).

No account needed: Aria POSTs to https://ntfy.sh/<topic>, and any phone
running the ntfy app subscribed to that topic gets an instant push.
The topic name is the only "secret" — treat it like a password.

Everything is best-effort and fire-and-forget: a dead network must never
block or crash a reminder.
"""

import secrets
import threading

import requests

import config as cfg
from core.logger import get_logger

log = get_logger("notify")


def enabled() -> bool:
    return bool(cfg.get("ntfy_enabled")) and bool((cfg.get("ntfy_topic") or "").strip())


def ensure_topic() -> str:
    """Return the configured topic, generating a private one on first use."""
    topic = (cfg.get("ntfy_topic") or "").strip()
    if not topic:
        user = (cfg.get("user_name") or "aria").split()[0].lower()
        topic = f"aria-{user}-{secrets.token_hex(3)}"
        cfg.set("ntfy_topic", topic)
    return topic


def _url() -> str:
    server = (cfg.get("ntfy_server") or "https://ntfy.sh").rstrip("/")
    return f"{server}/{(cfg.get('ntfy_topic') or '').strip()}"


def push_sync(title: str, message: str, priority: str = "default",
              tags: str = "robot") -> bool:
    """Send one push. Returns True on HTTP 200. Raises nothing."""
    if not (cfg.get("ntfy_topic") or "").strip():
        return False
    try:
        r = requests.post(
            _url(),
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": priority, "Tags": tags},
            timeout=10,
        )
        ok = r.status_code == 200
        if not ok:
            log.warning(f"ntfy push failed: HTTP {r.status_code} {r.text[:100]}")
        return ok
    except Exception as e:
        log.warning(f"ntfy push failed: {e}")
        return False


def push(title: str, message: str, priority: str = "default"):
    """Fire-and-forget push (background thread). No-op when disabled."""
    if not enabled():
        return
    threading.Thread(target=push_sync, args=(title, message, priority),
                     daemon=True).start()
