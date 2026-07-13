"""pyttsx3 TTS — non-blocking queue-based."""
import threading, queue, re
from core.logger import get_logger
log = get_logger("tts")
try: import pyttsx3; TTS_OK = True
except ImportError: TTS_OK = False

def _strip_md(text):
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)
    text = re.sub(r'\[[^\]]+\]\([^\)]+\)', '', text)
    text = re.sub(r'#{1,6}\s+', '', text)
    text = re.sub(r'\n+', ' ', text)
    return text.strip()

class TTSEngine:
    def __init__(self):
        self._q = queue.Queue(); self._enabled = True; self._engine = None
        if not TTS_OK: log.warning("pyttsx3 not installed"); return
        t = threading.Thread(target=self._run, daemon=True); t.start()

    def _run(self):
        try:
            self._engine = pyttsx3.init(); self._apply()
            log.info("TTS ready")
        except Exception as e: log.error(f"TTS init: {e}"); return
        while True:
            try:
                item = self._q.get(timeout=1)
                if item is None: break
                if self._enabled and self._engine:
                    self._engine.say(item); self._engine.runAndWait()
            except queue.Empty: continue
            except Exception as e: log.error(f"TTS: {e}")

    def _apply(self):
        from config import get
        if not self._engine: return
        try:
            self._engine.setProperty("rate", get("tts_rate"))
            self._engine.setProperty("volume", get("tts_volume"))
            voices = self._engine.getProperty("voices")
            idx = get("tts_voice_idx")
            if voices and 0 <= idx < len(voices):
                self._engine.setProperty("voice", voices[idx].id)
        except Exception as e: log.warning(f"TTS settings: {e}")

    def speak(self, text):
        if not TTS_OK or not self._enabled: return
        clean = _strip_md(text)
        if clean: self._q.put(clean)

    def stop(self):
        while not self._q.empty():
            try: self._q.get_nowait()
            except: break
        if self._engine:
            try: self._engine.stop()
            except: pass

    def set_enabled(self, v): self._enabled = v; not v and self.stop()
    def reload_settings(self): self._apply()
    def get_voices(self):
        if self._engine:
            try: return self._engine.getProperty("voices") or []
            except: pass
        return []
    def shutdown(self): self._q.put(None)
