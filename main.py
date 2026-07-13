"""
Aria — Production Entry Point
Boot order: logging → config → plugins → RAG → TTS → assistant → hotkey → UI → proactive → VAD → wake word → tray → mainloop
"""
import sys
import customtkinter as ctk
from core.logger import setup_logging, install_crash_handler, get_logger
setup_logging()
log = get_logger("main")
log.info("=" * 60)
log.info("Aria starting...")

import config as cfg
install_crash_handler(lambda msg: log.critical(f"Crash: {msg}"))

# CTkScrollbar reads _motion_center_offset in its motion handler but only sets it
# on click — a motion event arriving before a click raises AttributeError. A class
# default of 0 makes the attribute always resolvable (correct: click resets it to 0).
ctk.CTkScrollbar._motion_center_offset = 0

for pkg in ["customtkinter","requests"]:
    try: __import__(pkg)
    except ImportError: print(f"[ERROR] Missing: {pkg}\nRun: pip install -r requirements.txt"); sys.exit(1)

# ── Plugins ───────────────────────────────────────────────────────────────────
from core.plugin_manager import load_all as load_plugins
loaded = load_plugins()
log.info(f"Plugins: {loaded or 'none'}")

# ── MCP connectors (async — never blocks boot) ────────────────────────────────
from core import mcp_client
mcp_client.load_all_async()

# ── RAG ───────────────────────────────────────────────────────────────────────
from core.rag import RAGEngine
rag = RAGEngine()
log.info(f"RAG: {rag.chunk_count} chunks")

# ── Model router warm-up ──────────────────────────────────────────────────────
from core.model_router import _get_cached_installed
log.info(f"Ollama models: {_get_cached_installed()}")

# ── TTS ───────────────────────────────────────────────────────────────────────
from core.tts import TTSEngine
tts = TTSEngine()

# ── App ref + reminder callback ───────────────────────────────────────────────
ctk.set_appearance_mode("dark"); ctk.set_default_color_theme("blue")
_app_ref = [None]

def _on_reminder(title):
    log.info(f"Reminder: {title}")
    if _app_ref[0]: _app_ref[0].notify_reminder(title)

# ── Assistant ─────────────────────────────────────────────────────────────────
from core.assistant import Assistant
try:
    assistant = Assistant(on_reminder=_on_reminder)
    assistant._rag            = rag
    assistant._plugin_manager = type("PM", (), {
        "get_tool_descriptions": lambda s: load_plugins and __import__("core.plugin_manager", fromlist=["get_tool_descriptions"]).get_tool_descriptions(),
        "detect_and_execute":    lambda s, text: __import__("core.plugin_manager", fromlist=["detect_and_execute"]).detect_and_execute(text),
    })()
    log.info(f"Assistant ready — {cfg.get('ollama_model')}")
except RuntimeError as e:
    print(f"\n[ERROR] {e}\n"); sys.exit(1)

# ── Hotkey ────────────────────────────────────────────────────────────────────
from core.hotkey import HotkeyListener
hotkey = HotkeyListener(on_trigger=lambda: _app_ref[0] and _app_ref[0].toggle())

# ── Overlay ───────────────────────────────────────────────────────────────────
from ui.overlay import OverlayApp, _enable_drag_drop
app = OverlayApp(assistant, tts_engine=tts, hotkey_listener=hotkey)
_app_ref[0] = app

# ── Proactive ─────────────────────────────────────────────────────────────────
from core.proactive import ProactiveEngine
def _on_suggestion(msg, source):
    log.info(f"Proactive [{source}]: {msg[:60]}")
    def show():
        if not app._is_thinking:
            app._set_status(f"💡 {msg[:80]}")
            if source in ("morning","eod","monday","friday"):
                app._add_bubble("assistant", msg, "")
                if tts and cfg.get("tts_enabled"): tts.speak(msg[:150])
    app.after(0, show)

proactive = ProactiveEngine(on_suggestion=_on_suggestion)
proactive.start()

# ── Background thinker (autonomous reflection) ────────────────────────────────
from core.background_thinker import BackgroundThinker
def _on_thought(msg, source):
    log.info(f"Thought surfaced: {msg[:60]}")
    def show():
        if not app._is_thinking:
            app._add_bubble("assistant", msg, "")
            app._set_status("💭 A thought…")
            if tts and cfg.get("tts_enabled"): tts.speak(msg.lstrip("💭 ")[:150])
    app.after(0, show)

thinker = BackgroundThinker(on_thought=_on_thought)
thinker.start()

_orig = app._on_send
def _patched(e=None): proactive.ping(); thinker.ping(); _orig(e)
app._on_send = _patched

# ── VAD ───────────────────────────────────────────────────────────────────────
from core.vad import VADRecorder

def _on_vad_speech(audio_bytes):
    if app._is_thinking or not cfg.get("vad_enabled"): return
    import wave, tempfile, os
    if not (hasattr(app.voice, "_model") and app.voice._model_loaded): return
    tmp = tempfile.mktemp(suffix=".wav")
    try:
        with wave.open(tmp,"wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000); wf.writeframes(audio_bytes)
        segs, _ = app.voice._model.transcribe(tmp, beam_size=3, vad_filter=True)
        text = " ".join(s.text for s in segs).strip()
        if text:
            log.info(f"VAD: {text}")
            app.after(0, lambda t=text: app._inject_voice(t))
    except Exception as e: log.error(f"VAD transcribe: {e}")
    finally:
        try: os.unlink(tmp)
        except: pass

vad = VADRecorder(on_speech_ready=_on_vad_speech)
if cfg.get("vad_enabled"):
    vad.start(); log.info("VAD started")
    if tts:
        _orig_speak = tts.speak
        def _speak_mute(text):
            vad.mute(); _orig_speak(text)
            import threading
            threading.Timer(max(2, len(text.split())/(cfg.get("tts_rate")/60))+0.5, vad.unmute).start()
        tts.speak = _speak_mute

# ── Wake word ─────────────────────────────────────────────────────────────────
from core.wake_word import WakeWordDetector
def _on_wake():
    log.info("Wake word!")
    def activate():
        app.show()
        if cfg.get("vad_enabled"): app._set_status("🎙️ Listening...")
        else:
            app._mic_press()
            import threading, time
            def rel(): time.sleep(4); app.after(0, app._mic_release); wake.resume()
            threading.Thread(target=rel, daemon=True).start(); return
        import threading, time
        threading.Timer(8, wake.resume).start()
    app.after(0, activate)

wake = WakeWordDetector(on_wake=_on_wake, wake_word=cfg.get("wake_word"), threshold=cfg.get("wake_threshold"))
if cfg.get("wake_word_enabled"): wake.start()

# ── Tray ──────────────────────────────────────────────────────────────────────
from ui.tray import TrayIcon
tray = TrayIcon(
    on_show=lambda: app.after(0, app.show),
    on_quit=lambda: (tts.shutdown(), app.after(0, app.destroy)),
    on_settings=lambda: app.after(0, app._open_settings),
    assistant_name=cfg.get("assistant_name"),
)
tray.start()

# ── Hotkey + drag-drop ────────────────────────────────────────────────────────
hotkey.start(cfg.get("hotkey"))
_enable_drag_drop(app)

if cfg.get("tts_enabled"): tts.speak(f"{cfg.get('assistant_name')} is ready.")
log.info("All systems online.")

try: app.mainloop()
except KeyboardInterrupt: log.info("Keyboard interrupt")
finally:
    log.info("Shutting down...")
    proactive.stop(); thinker.stop(); vad.stop(); wake.stop()
    tts.shutdown(); hotkey.stop(); tray.stop(); mcp_client.stop_all()
    if assistant._reminder_engine: assistant._reminder_engine.shutdown()
    log.info("Done.")
