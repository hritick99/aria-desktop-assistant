"""
MCP connector client — the same plugin ecosystem Claude desktop uses.

Each configured server (Settings → Connectors) is spawned as a subprocess
speaking JSON-RPC 2.0 over newline-delimited stdio (the MCP stdio
transport). After the initialize handshake we fetch its tool list; tools
are exposed to the model as tags:

    [MCP: <server>.<tool> | {"argument": "value"}]

Everything is best-effort: a connector that fails to start is logged and
skipped, and never blocks the assistant.
"""

import json
import os
import re
import shlex
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

import config as cfg
from core.logger import get_logger

log = get_logger("mcp")

_PROTOCOL = "2025-06-18"
_servers: Dict[str, "MCPServer"] = {}
_lock = threading.Lock()


def _augmented_env(extra: dict = None) -> dict:
    """Child env with Node/npx on PATH (winget installs it off the default
    PATH for already-running shells) plus any per-server env (tokens)."""
    import glob
    env = dict(os.environ)
    dirs = []
    la = env.get("LOCALAPPDATA", "")
    if la:
        dirs += glob.glob(os.path.join(la, "Microsoft", "WinGet", "Packages",
                                       "OpenJS.NodeJS*", "node-*"))
        dirs.append(os.path.join(la, "Programs", "nodejs"))
    dirs.append(r"C:\Program Files\nodejs")
    have = env.get("PATH", "")
    for d in dirs:
        if os.path.isdir(d) and d not in have:
            env["PATH"] = d + os.pathsep + env.get("PATH", "")
    if extra:
        for k, v in extra.items():
            if v:
                env[str(k)] = str(v)
    return env


class MCPServer:
    def __init__(self, name: str, command: str, env: dict = None):
        self.name = name
        self.command = command
        self.env = env or {}
        self.tools: List[dict] = []
        self._proc = None
        self._id = 0
        self._io_lock = threading.Lock()

    def start(self):
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._proc = subprocess.Popen(
            self.command if os.name == "nt" else shlex.split(self.command),
            shell=(os.name == "nt"),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", creationflags=flags,
            env=_augmented_env(self.env),
        )
        self._request("initialize", {
            "protocolVersion": _PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "aria", "version": "1.0"},
        }, timeout=30)
        self._notify("notifications/initialized")
        res = self._request("tools/list", {}, timeout=30)
        self.tools = res.get("tools", [])
        log.info(f"Connector '{self.name}': {len(self.tools)} tools")

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _send(self, msg: dict):
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()

    def _notify(self, method: str):
        self._send({"jsonrpc": "2.0", "method": method})

    def _request(self, method: str, params: dict, timeout: float = 60) -> dict:
        with self._io_lock:
            self._id += 1
            rid = self._id
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            deadline = time.time() + timeout
            while time.time() < deadline:
                line = self._proc.stdout.readline()
                if not line:
                    raise RuntimeError("connector closed its stdout")
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("id") == rid:
                    if "error" in msg:
                        raise RuntimeError(msg["error"].get("message", "MCP error"))
                    return msg.get("result", {})
                # other ids / server notifications — ignore
            raise TimeoutError(f"{method} timed out after {timeout}s")

    def call_tool(self, tool: str, args: dict) -> str:
        res = self._request("tools/call", {"name": tool, "arguments": args}, timeout=90)
        parts = [c.get("text", "") for c in res.get("content", [])
                 if c.get("type") == "text"]
        text = "\n".join(p for p in parts if p)
        return text or json.dumps(res)[:2000]

    def stop(self):
        try:
            if self._proc:
                self._proc.terminate()
        except Exception:
            pass


# ── module-level manager ────────────────────────────────────────────────────

def load_all():
    """(Re)connect every enabled connector from config. Blocking."""
    stop_all()
    for entry in cfg.get("mcp_servers") or []:
        name, command = entry.get("name", "").strip(), entry.get("command", "").strip()
        if not name or not command or not entry.get("enabled", True):
            continue
        env = dict(entry.get("env") or {})
        # Always use the CURRENT GitHub token for github connectors.
        if "server-github" in command or name.lower() == "github":
            tok = (cfg.get("github_token") or "").strip()
            if tok:
                env["GITHUB_PERSONAL_ACCESS_TOKEN"] = tok
                env.setdefault("GITHUB_TOKEN", tok)
        srv = MCPServer(name, command, env=env)
        try:
            srv.start()
            with _lock:
                _servers[name] = srv
        except Exception as e:
            srv.stop()
            log.error(f"Connector '{name}' failed to start: {e}")


def load_all_async():
    threading.Thread(target=load_all, daemon=True).start()


def stop_all():
    with _lock:
        for s in _servers.values():
            s.stop()
        _servers.clear()


def status() -> List[dict]:
    with _lock:
        return [{"name": s.name, "tools": len(s.tools), "alive": s.alive()}
                for s in _servers.values()]


def get_tool_descriptions() -> str:
    with _lock:
        servers = [s for s in _servers.values() if s.alive() and s.tools]
    if not servers:
        return ""
    lines = [
        "",
        "--- CONNECTORS (MCP) ---",
        'To use a connector tool, output: [MCP: <server>.<tool> | {"arg": "value"}]',
    ]
    for s in servers:
        for t in s.tools:
            desc = (t.get("description") or "").split("\n")[0][:110]
            lines.append(f"- {s.name}.{t.get('name')}: {desc}")
    return "\n".join(lines)


_TAG = re.compile(r'\[MCP:\s*([\w\-]+)\.([\w\-\.]+)\s*(?:\|\s*(\{.*?\}))?\s*\]', re.I | re.S)


def detect_and_execute(text: str) -> Optional[Tuple[str, str]]:
    """Find an [MCP: …] tag in model output and run it. Returns (label, result)."""
    m = _TAG.search(text or "")
    if not m:
        return None
    server, tool, raw_args = m.group(1), m.group(2), m.group(3)
    label = f"{server}.{tool}"
    with _lock:
        srv = _servers.get(server)
    if not srv or not srv.alive():
        return label, f"Connector '{server}' is not connected."
    try:
        args = json.loads(raw_args) if raw_args else {}
    except ValueError:
        return label, "Invalid JSON arguments in [MCP: …] tag."
    try:
        return label, srv.call_tool(tool, args)
    except Exception as e:
        log.error(f"Connector call {label}: {e}")
        return label, f"Connector error: {e}"
