"""Global hotkey listener via pynput."""
import threading
from typing import Callable
from core.logger import get_logger
log = get_logger("hotkey")
try: from pynput import keyboard; PYNPUT_OK = True
except ImportError: PYNPUT_OK = False

class HotkeyListener:
    def __init__(self, on_trigger: Callable):
        self.on_trigger = on_trigger; self._listener = None; self._hotkey = None

    def start(self, hotkey_str: str = "<alt>+<space>"):
        self._hotkey = hotkey_str
        if not PYNPUT_OK: log.warning("pynput not installed — hotkey disabled"); return
        def run():
            try:
                with keyboard.GlobalHotKeys({hotkey_str: self._handle}) as l:
                    self._listener = l; l.join()
            except Exception as e: log.error(f"Hotkey: {e}")
        threading.Thread(target=run, daemon=True).start()
        log.info(f"Hotkey: {hotkey_str}")

    def _handle(self):
        try: self.on_trigger()
        except Exception as e: log.error(f"Hotkey handler: {e}")

    def stop(self):
        if self._listener:
            try: self._listener.stop()
            except: pass

    def restart(self, new_hotkey: str): self.stop(); self.start(new_hotkey)
