"""Proactive engine — clipboard watcher, idle detector, time triggers."""
import threading, time, re
from datetime import datetime, date
from typing import Callable, Optional
from core.logger import get_logger
log = get_logger("proactive")

class ProactiveEngine:
    def __init__(self, on_suggestion: Callable[[str, str], None]):
        self.on_suggestion = on_suggestion
        self._running = False; self._last_activity = time.time()
        self._idle_notified = False; self._morning_date = None
        self._last_clipboard = ""; self._threads = []

    def start(self):
        self._running = True
        for name, fn in [("clipboard",self._clipboard_loop),("idle",self._idle_loop),("time",self._time_loop)]:
            t = threading.Thread(target=fn, daemon=True, name=f"proactive_{name}"); t.start(); self._threads.append(t)
        log.info("Proactive engine started")

    def ping(self): self._last_activity = time.time(); self._idle_notified = False

    def stop(self): self._running = False

    def _clipboard_loop(self):
        try: import pyperclip
        except ImportError: return
        last_suggest = 0
        while self._running:
            time.sleep(2)
            try: content = pyperclip.paste() or ""
            except: continue
            if (content != self._last_clipboard and len(content) > 40
                    and time.time() - last_suggest > 30 and not self._looks_pw(content)):
                self._last_clipboard = content; last_suggest = time.time()
                preview = content[:60].replace("\n"," ")
                self.on_suggestion(f'📋 New clipboard — want me to summarise it?\n"{preview}..."', "clipboard")

    def _looks_pw(self, text):
        text = text.strip()
        if "\n" in text or " " in text[:20] or not (8 <= len(text) <= 64): return False
        score = sum([any(c.isupper() for c in text), any(c.islower() for c in text),
                     any(c.isdigit() for c in text), any(c in "!@#$%^&*_-+=" for c in text)])
        return score >= 3 and len(text) >= 12

    def _idle_loop(self):
        while self._running:
            time.sleep(60)
            if time.time() - self._last_activity > 25*60 and not self._idle_notified:
                self._idle_notified = True
                if 9 <= datetime.now().hour <= 22:
                    import random
                    self.on_suggestion(random.choice([
                        "🌿 You've been away — need help picking up where we left off?",
                        "☕ Welcome back! Anything to catch up on?",
                    ]), "idle")

    def _time_loop(self):
        while self._running:
            time.sleep(60)
            now = datetime.now(); h = now.hour; m = now.minute; today = date.today()
            if h == 9 and m < 5 and self._morning_date != today:
                self._morning_date = today
                self.on_suggestion(f"🌅 Good morning! It's {now.strftime('%A')}. Want your daily briefing?", "morning")
            elif h == 18 and m < 5:
                self.on_suggestion("🌇 End of day! Want a quick review or set reminders for tomorrow?", "eod")
            elif now.weekday() == 0 and h == 9 and 5 <= m < 10:
                self.on_suggestion("📅 New week! Want help planning priorities?", "monday")
            elif now.weekday() == 4 and h == 17 and m < 5:
                self.on_suggestion("🎉 Friday! Want a week wrap-up?", "friday")
