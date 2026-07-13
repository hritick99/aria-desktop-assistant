"""openWakeWord always-listening wake word detector."""
import threading, numpy as np
from typing import Callable, Optional
from core.logger import get_logger
log = get_logger("wake_word")
try: from openwakeword.model import Model as OWWModel; OWW_OK = True
except ImportError: OWW_OK = False
try: import pyaudio; PA_OK = True
except ImportError: PA_OK = False

CHUNK = 1280; SAMPLE_RATE = 16000
MODEL_MAP = {"hey aria":"hey_jarvis","hey jarvis":"hey_jarvis","alexa":"alexa","ok google":"ok_google"}

class WakeWordDetector:
    def __init__(self, on_wake: Callable, wake_word: str = "hey aria", threshold: float = 0.5):
        self.on_wake = on_wake; self.wake_word = wake_word; self.threshold = threshold
        self._running = False; self._paused = False; self._model = None

    def start(self):
        if not OWW_OK: log.warning("openWakeWord not installed — pip install openwakeword"); return
        if not PA_OK:  log.warning("pyaudio not installed"); return
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()
        log.info(f"Wake word started: '{self.wake_word}'")

    def _load(self):
        try:
            name = MODEL_MAP.get(self.wake_word.lower(), "hey_jarvis")
            self._model = OWWModel(wakeword_models=[name], inference_framework="onnx")
            log.info(f"Wake model: {name}"); return True
        except Exception as e:
            log.error(f"Wake model load: {e}\nRun: python -m openwakeword.utils download_models")
            return False

    def _run(self):
        if not self._load(): return
        pa = pyaudio.PyAudio()
        try: stream = pa.open(rate=SAMPLE_RATE, channels=1, format=pyaudio.paInt16,
                              input=True, frames_per_buffer=CHUNK)
        except Exception as e: log.error(f"Wake mic: {e}"); pa.terminate(); return
        hits = 0
        while self._running:
            try:
                if self._paused: threading.Event().wait(0.1); continue
                data = stream.read(CHUNK, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.int16)
                pred  = self._model.predict(audio)
                score = max(pred.values()) if pred else 0.0
                if score >= self.threshold:
                    hits += 1
                    if hits >= 2:
                        hits = 0; self._paused = True
                        try: self.on_wake()
                        except Exception as e: log.error(f"Wake handler: {e}")
                else: hits = 0
            except Exception as e:
                if self._running: log.error(f"Wake loop: {e}"); break
        stream.stop_stream(); stream.close(); pa.terminate()

    def resume(self): self._paused = False
    def stop(self):   self._running = False
