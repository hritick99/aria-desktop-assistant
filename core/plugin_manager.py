"""Plugin manager — auto-load .py files from plugins/ directory."""
import os, re, importlib.util
from typing import Dict, List, Optional, Tuple
from core.logger import get_logger
log = get_logger("plugins")

PLUGINS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")
_loaded: Dict[str, object] = {}

def load_all() -> List[str]:
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    loaded = []
    for fname in sorted(os.listdir(PLUGINS_DIR)):
        if fname.startswith("_") or not fname.endswith(".py"): continue
        path = os.path.join(PLUGINS_DIR, fname); name = fname[:-3]
        try:
            spec = importlib.util.spec_from_file_location(f"plugin_{name}", path)
            mod  = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            required = ["PLUGIN_NAME","PLUGIN_DESCRIPTION","TOOL_TAG_PATTERN","TOOL_DESCRIPTION","execute"]
            missing  = [r for r in required if not hasattr(mod, r)]
            if missing: log.warning(f"Plugin {fname} missing: {missing}"); continue
            _loaded[mod.PLUGIN_NAME] = mod
            if hasattr(mod, "on_load"): mod.on_load()
            loaded.append(mod.PLUGIN_NAME); log.info(f"Plugin: {mod.PLUGIN_NAME}")
        except Exception as e: log.error(f"Plugin load [{fname}]: {e}")
    return loaded

def get_tool_descriptions() -> str:
    if not _loaded: return ""
    return "\n--- PLUGINS ---\n" + "\n".join(p.TOOL_DESCRIPTION for p in _loaded.values())

def detect_and_execute(text: str) -> Optional[Tuple[str, str]]:
    for name, plugin in _loaded.items():
        m = re.search(plugin.TOOL_TAG_PATTERN, text, re.I | re.S)
        if m:
            arg = m.group(1).strip() if m.lastindex else ""
            try: return name, plugin.execute(arg)
            except Exception as e: return name, f"Plugin error: {e}"
    return None

def list_plugins() -> List[Dict]:
    return [{"name":p.PLUGIN_NAME,"description":p.PLUGIN_DESCRIPTION} for p in _loaded.values()]
