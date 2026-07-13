"""WebRTC VAD — always-listening auto-recording."""
import threading, collections, time, wave, tempfile, os
import numpy as np
from typing import Callable, Optional
from core.logger import get_logger
log = get_logger("vad")
try: import webrtcvad; VAD_OK = True
except ImportError: VAD_OK = False
try: import pyaudio; PA_OK = True
except ImportError: PA_OK = False

SAMPLE_RATE = 16000; FRAME_MS = 30; CHUNK = int(SAMPLE_RATE * FRAME_MS / 1000)
SILENCE_TIMEOUT = 1.2; MIN_SPEECH = 0.4; MAX_SECS = 30

class VADRecorder:
    def __init__(self, on_speech_ready: Callable[[bytes], None], aggressiveness: int = 2):
        self.on_speech_ready = on_speech_ready; self._agg = aggressiveness
        self._running = False; self._muted = False
        if not VAD_OK: log.warning("webrtcvad-wheels not installed")
        if not PA_OK:  log.warning("pyaudio not installed")

    @property
    def available(self): return VAD_OK and PA_OK

    def start(self):
        if not self.available: return
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()
        log.info("VAD started")

    def mute(self):   self._muted = True
    def unmute(self): self._muted = False

    def _run(self):
        vad = webrtcvad.Vad(self._agg)
        pa  = pyaudio.PyAudio()
        try:
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE,
                             input=True, frames_per_buffer=CHUNK)
        except Exception as e: log.error(f"VAD mic: {e}"); pa.terminate(); return
        ring = collections.deque(maxlen=15); triggered = False
        frames = []; silence_start = None
        while self._running:
            try:
                frame = stream.read(CHUNK, exception_on_overflow=False)
                if self._muted: ring.clear(); continue
                is_speech = vad.is_speech(frame, SAMPLE_RATE)
                if not triggered:
                    ring.append((frame, is_speech))
                    if sum(1 for _,s in ring if s) > 0.9 * ring.maxlen:
                        triggered = True; frames = [f for f,_ in ring]; ring.clear(); silence_start = None
                else:
                    frames.append(frame)
                    if not is_speech:
                        if silence_start is None: silence_start = time.time()
                        elif time.time() - silence_start > SILENCE_TIMEOUT:
                            triggered = False; silence_start = None
                            dur = len(frames) * FRAME_MS / 1000
                            if dur >= MIN_SPEECH:
                                audio = b"".join(frames)
                                threading.Thread(target=self.on_speech_ready, args=(audio,), daemon=True).start()
                            frames = []
                    else: silence_start = None
                    if len(frames)*FRAME_MS/1000 > MAX_SECS:
                        audio = b"".join(frames); frames = []; triggered = False
                        threading.Thread(target=self.on_speech_ready, args=(audio,), daemon=True).start()
            except Exception as e:
                if self._running: log.error(f"VAD loop: {e}")
        stream.stop_stream(); stream.close(); pa.terminate()

    def stop(self): self._running = False
