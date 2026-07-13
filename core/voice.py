"""Push-to-talk voice capture + faster-whisper STT."""
import os, wave, tempfile, threading
import numpy as np
from typing import Optional, Callable
from core.logger import get_logger
log = get_logger("voice")
try: import pyaudio; PA_OK = True
except ImportError: PA_OK = False
try: from faster_whisper import WhisperModel; W_OK = True
except ImportError: W_OK = False

SAMPLE_RATE = 16000; CHANNELS = 1; CHUNK = 1024

class VoiceRecorder:
    def __init__(self, on_status: Optional[Callable] = None):
        self.on_status = on_status or (lambda m: None)
        self._recording = False; self._frames = []; self._thread = None
        self._pa = None; self._stream = None; self._model = None
        self._model_loaded = False
        if not PA_OK: self.on_status("pyaudio not installed"); return
        if not W_OK:  self.on_status("faster-whisper not installed"); return
        threading.Thread(target=self._load_model, daemon=True).start()

    def _load_model(self):
        from config import get
        self.on_status(f"Loading Whisper '{get('whisper_model')}'...")
        try:
            self._model = WhisperModel(get("whisper_model"), device="cpu", compute_type="int8")
            self._model_loaded = True; self.on_status("Voice ready")
        except Exception as e: self.on_status(f"Whisper failed: {e}")

    @property
    def ready(self): return PA_OK and W_OK and self._model_loaded

    def start_recording(self):
        if not self.ready or self._recording: return False
        self._frames = []; self._recording = True
        try:
            self._pa = pyaudio.PyAudio()
            self._stream = self._pa.open(format=pyaudio.paInt16, channels=CHANNELS,
                rate=SAMPLE_RATE, input=True, frames_per_buffer=CHUNK)
        except Exception as e: self.on_status(f"Mic error: {e}"); self._recording=False; return False
        self._thread = threading.Thread(target=self._capture, daemon=True); self._thread.start()
        self.on_status("🎙️ Recording..."); return True

    def _capture(self):
        while self._recording:
            try: self._frames.append(self._stream.read(CHUNK, exception_on_overflow=False))
            except: break

    def stop_and_transcribe(self):
        if not self._recording: return None
        self._recording = False
        if self._thread: self._thread.join(timeout=2)
        try:
            if self._stream: self._stream.stop_stream(); self._stream.close()
            if self._pa: self._pa.terminate()
        except: pass
        if not self._frames: self.on_status("No audio"); return None
        audio = b"".join(self._frames)
        arr = np.frombuffer(audio, dtype=np.int16)
        if np.sqrt(np.mean(arr.astype(np.float32)**2)) < 300:
            self.on_status("Silence detected"); return None
        self.on_status("Transcribing...")
        return self._transcribe(audio)

    def _transcribe(self, audio):
        tmp = tempfile.mktemp(suffix=".wav")
        try:
            with wave.open(tmp, "wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000); wf.writeframes(audio)
            segs, _ = self._model.transcribe(tmp, beam_size=3, language=None, vad_filter=True)
            text = " ".join(s.text for s in segs).strip()
            self.on_status("Voice ready"); return text or None
        except Exception as e: self.on_status(f"Transcription error: {e}"); return None
        finally:
            try: os.unlink(tmp)
            except: pass
