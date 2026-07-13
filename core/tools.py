"""
Tools — web search, code exec, clipboard, screenshot.
"""

import os
import sys
import base64
import io
import re
import subprocess
import tempfile
from typing import Optional, Tuple
from core.logger import get_logger

log = get_logger("tools")


def web_search(query: str, max_results: int = 5) -> str:
    try:
        try:
            from ddgs import DDGS          # current package
        except ImportError:
            from duckduckgo_search import DDGS  # legacy fallback
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(f"**{r.get('title','')}**\n{r.get('body','')[:300]}\n{r.get('href','')}")
        return "\n\n---\n\n".join(results) if results else "No results found."
    except ImportError:
        return "ddgs not installed — run: pip install ddgs"
    except Exception as e:
        return f"Search error: {e}"


def run_code(code: str, timeout: int = 15) -> str:
    import textwrap
    import config as cfg
    code = textwrap.dedent(code).strip()
    if not cfg.get("full_control"):
        dangerous = ["import os", "import sys", "import subprocess", "import shutil",
                     "rmdir", "remove(", "unlink(", "__import__"]
        flagged = [d for d in dangerous if d in code]
        if flagged:
            return (f"⚠️ Blocked — unsafe patterns: {', '.join(flagged)} "
                    "(enable 'Full computer control' in Settings to allow)")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        tmp = f.name
    try:
        result = subprocess.run([sys.executable, tmp], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout)
        out = result.stdout.strip()
        err = "\n".join(l for l in result.stderr.splitlines()
                        if "DeprecationWarning" not in l)
        parts = []
        if out: parts.append(f"Output:\n{out}")
        if err.strip(): parts.append(f"Errors:\n{err.strip()}")
        return "\n".join(parts) if parts else "(no output)"
    except subprocess.TimeoutExpired:
        return f"⏱️ Timed out after {timeout}s"
    except Exception as e:
        return f"Execution error: {e}"
    finally:
        try: os.unlink(tmp)
        except: pass


def get_clipboard() -> str:
    try:
        import pyperclip
        text = pyperclip.paste()
        return text if text else "(clipboard is empty)"
    except ImportError:
        return "pyperclip not installed."
    except Exception as e:
        return f"Clipboard error: {e}"


def take_screenshot(region=None) -> Tuple[str, str]:
    try:
        import mss
        from PIL import Image
        with mss.mss() as sct:
            monitor = {"left": region[0], "top": region[1],
                       "width": region[2], "height": region[3]} if region else sct.monitors[1]
            img = Image.frombytes("RGB", sct.grab(monitor).size,
                                  sct.grab(monitor).bgra, "raw", "BGRX")
        if img.width > 1280:
            ratio = 1280 / img.width
            img = img.resize((1280, int(img.height * ratio)))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()
        from datetime import datetime
        return b64, f"Screenshot taken at {datetime.now().strftime('%H:%M:%S')}"
    except ImportError as e:
        return "", f"Missing: {e}"
    except Exception as e:
        return "", f"Screenshot error: {e}"


TOOL_DESCRIPTIONS = """
AVAILABLE TOOLS (emit exactly one per response when needed):

1. [SEARCH: query]          → Web search via DuckDuckGo
2. [CODE: python_code]      → Run Python (sandboxed)
3. [CLIPBOARD]              → Read clipboard
4. [SCREENSHOT]             → Capture screen (needs vision model)
5. [REMINDER: HH:MM | once|daily|weekdays | title]  → Schedule reminder
6. [FILE: /path/to/file]    → Read file (PDF/docx/xlsx/txt/code)
7. [OS: action | args]      → OS control (open/type/press/volume/kill/url)
8. [RAG: query]             → Search your indexed local documents
9. [REMEMBER: entity | fact]        → Save a durable fact to memory, e.g.
   [REMEMBER: Hritick | birthday is in March]. Relationships:
   [REMEMBER: Hritick | owns | RTX 4060]
10. [REMINDERS: list]        → Manage existing reminders. Also:
   [REMINDERS: done | title]              → mark one completed
   [REMINDERS: delete | title]            → cancel one
   [REMINDERS: snooze | title | minutes]  → re-fire it later

Rules:
- Use exactly ONE tool per response.
- Emit the tag exactly as shown.
- After tool result is provided, give a direct helpful answer.
- Never fabricate tool results.
"""
