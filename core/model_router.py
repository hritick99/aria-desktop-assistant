"""Route queries to best available Ollama model by intent."""
import re, requests
from typing import Optional
from core.logger import get_logger
import config as cfg
log = get_logger("model_router")

_VISION    = [r'\bscreen\b',r'\bscreenshot\b',r'\blook at\b',r'\bimage\b']
_CODE      = [r'\bcode\b',r'\bfunction\b',r'\bscript\b',r'\bdebug\b',r'\bpython\b',r'\bjavascript\b',r'\bimplement\b']
_REASONING = [r'\banalyse\b',r'\banalyze\b',r'\bcompare\b',r'\bpros and cons\b',r'\bexplain why\b',r'\bmath\b']
_FAST      = [r'^(what is|who is|when|where|define|hi|hey|thanks|remind)\b']

_installed_cache = None

def _installed():
    global _installed_cache
    if _installed_cache is None:
        try:
            r = requests.get(f"{cfg.get('ollama_base_url')}/api/tags", timeout=3)
            _installed_cache = [m["name"] for m in r.json().get("models", [])]
        except: _installed_cache = []
    return _installed_cache

def detect_intent(msg: str) -> str:
    m = msg.lower()
    if any(re.search(p, m) for p in _VISION):    return "vision"
    if any(re.search(p, m) for p in _CODE):      return "code"
    if any(re.search(p, m) for p in _FAST):      return "fast"
    if any(re.search(p, m) for p in _REASONING): return "reasoning"
    if len(msg.split()) > 30:                     return "reasoning"
    return "default"

def route(message: str) -> str:
    intent   = detect_intent(message)
    pref_map = {"vision":cfg.get("model_vision"),"code":cfg.get("model_code"),
                "reasoning":cfg.get("model_reasoning"),"fast":cfg.get("model_fast"),
                "default":cfg.get("ollama_model")}
    preferred = pref_map.get(intent, cfg.get("ollama_model"))
    default   = cfg.get("ollama_model")
    if preferred == default: return default
    base = preferred.split(":")[0]
    for m in _installed():
        if m.startswith(base) or m == preferred:
            log.info(f"Router: {intent} → {m}"); return m
    return default

# Alias used in main.py
def _get_cached_installed(): return _installed()
