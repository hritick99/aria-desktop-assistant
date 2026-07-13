"""OS control — open apps, type, press keys, volume, kill processes. Windows + Linux."""
import os, sys, platform, subprocess, webbrowser
from typing import Tuple
from core.logger import get_logger
log = get_logger("os_control")
IS_WIN = platform.system() == "Windows"
IS_LIN = platform.system() == "Linux"

ALLOWED = {"notepad","explorer","chrome","firefox","edge","code","vscode","terminal","cmd",
           "powershell","bash","python","calculator","calc","spotify","vlc","paint",
           "slack","discord","telegram","zoom","teams","obs","files","nautilus","gimp"}

def execute_os_command(action: str, args: str = "") -> str:
    action = action.strip().lower(); args = args.strip()
    try:
        if action == "open":        return _open(args)
        elif action == "type":      return _type(args)
        elif action == "press":     return _press(args)
        elif action == "volume":    return _volume(args)
        elif action == "kill":      return _kill(args)
        elif action == "url":       return _url(args)
        elif action == "processes": return _procs()
        elif action == "active_window": return _active_win()
        elif action in ("shell", "run", "cmd", "command", "terminal"):
            # models sometimes nest: [OS: shell | SHELL: ipconfig]
            import re as _re
            return run_shell(_re.sub(r'^\s*shell:\s*', '', args, flags=_re.I))
        else: return f"Unknown OS action: '{action}'"
    except Exception as e: log.error(f"OS [{action}]: {e}"); return f"OS error: {e}"

def _open(name):
    n = name.lower().strip()
    if IS_WIN:
        cmds = {"chrome":"start chrome","firefox":"start firefox","edge":"start msedge",
                "code":"code","vscode":"code","calc":"calc","calculator":"calc",
                "notepad":"notepad","explorer":"explorer","cmd":"start cmd","powershell":"start powershell"}
        # Known shortcut, else let the Start-menu resolver find any installed app
        cmd = cmds.get(n, f'start "" "{name.strip()}"')
        subprocess.Popen(cmd, shell=True); return f"Opened {name}"
    else:
        cmds = {"chrome":"google-chrome","firefox":"firefox","code":"code","vscode":"code",
                "terminal":"x-terminal-emulator","files":"nautilus","calculator":"gnome-calculator"}
        subprocess.Popen([cmds.get(n, n)], start_new_session=True); return f"Opened {name}"

def _type(text):
    try:
        import pyautogui, time; time.sleep(0.3)
        pyautogui.write(text, interval=0.03)
        return f"Typed: {text[:50]}"
    except ImportError: return "pyautogui not installed."

def _press(combo):
    try:
        import pyautogui, time; time.sleep(0.2)
        keys = [k.strip() for k in combo.split("+")]
        pyautogui.press(keys[0]) if len(keys)==1 else pyautogui.hotkey(*keys)
        return f"Pressed: {combo}"
    except ImportError: return "pyautogui not installed."

def _volume(level_str):
    try: level = max(0, min(100, int(level_str)))
    except: return f"Invalid volume: {level_str}"
    if IS_WIN:
        try:
            try:
                import comtypes
                comtypes.CoInitialize()   # tool runs on a worker thread
            except Exception:
                pass
            from pycaw.pycaw import AudioUtilities
            dev = AudioUtilities.GetSpeakers()
            vol = getattr(dev, "EndpointVolume", None)   # pycaw ≥ 2023
            if vol is None:                              # legacy pycaw
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import IAudioEndpointVolume
                interface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                vol = cast(interface, POINTER(IAudioEndpointVolume))
            vol.SetMasterVolumeLevelScalar(level/100.0, None)
            return f"Volume: {level}%"
        except Exception as e:
            return f"Volume failed: {e}"
    else:
        try:
            subprocess.run(["pactl","set-sink-volume","@DEFAULT_SINK@",f"{level}%"], check=True, capture_output=True)
            return f"Volume: {level}%"
        except Exception as e: return f"Volume failed: {e}"

def _kill(name):
    protected = {"system","explorer","python","pythonw","svchost","init","systemd","bash"}
    if name.lower() in protected: return f"Cannot kill protected: {name}"
    if IS_WIN:
        r = subprocess.run(["taskkill","/F","/IM",name if name.endswith(".exe") else f"{name}.exe"],
                           capture_output=True, text=True)
        return r.stdout.strip() or r.stderr.strip() or f"Kill sent: {name}"
    else:
        subprocess.run(["pkill","-f",name], capture_output=True)
        return f"Kill signal sent: {name}"

def _url(url):
    if not url.startswith(("http://","https://")): url = "https://" + url
    webbrowser.open(url); return f"Opened: {url}"

def _procs():
    if IS_WIN:
        r = subprocess.run(["tasklist","/FO","CSV","/NH"], capture_output=True, text=True)
        lines = r.stdout.strip().splitlines()[:20]
        procs = []
        for l in lines:
            parts = l.strip('"').split('","')
            if parts: procs.append(f"{parts[0]:30s} PID:{parts[1] if len(parts)>1 else '?'}")
        return "Processes:\n" + "\n".join(procs)
    else:
        r = subprocess.run(["ps","aux","--sort=-%mem"], capture_output=True, text=True)
        return "Processes:\n" + "\n".join(r.stdout.splitlines()[:21])

def _active_win():
    if IS_WIN:
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            l = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(l+1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, l+1)
            return f"Active window: {buf.value}"
        except Exception as e: return f"Error: {e}"
    else:
        try:
            r = subprocess.run(["xdotool","getactivewindow","getwindowname"], capture_output=True, text=True)
            return f"Active window: {r.stdout.strip()}"
        except: return "xdotool not installed: sudo apt install xdotool"

# ── Terminal ─────────────────────────────────────────────────────────────────
_SHELL_BLOCK = ("format ", "diskpart", "cipher /w", "rm -rf /", "shutdown",
                "restart-computer", "stop-computer", "reg delete", "bcdedit",
                "vssadmin delete", "mkfs", "dd if=", "del /f /s /q c:",
                "rd /s /q c:", "remove-item -recurse c:")


def is_destructive_shell(cmd: str) -> bool:
    low = " ".join((cmd or "").lower().split())
    return any(b in low for b in _SHELL_BLOCK)


def run_shell(cmd: str, timeout: int = 30, confirmed: bool = False) -> str:
    """Run one terminal command (PowerShell on Windows, bash elsewhere)."""
    cmd = (cmd or "").strip()
    if not cmd:
        return "SHELL needs a command, e.g. [SHELL: Get-Date]"
    import config as cfg
    if not confirmed and is_destructive_shell(cmd):
        if not cfg.get("full_control"):
            return (f"⚠️ Blocked — command looks destructive: {cmd}\n"
                    "(enable 'Full computer control' in Settings to allow)")
        if cfg.get("confirm_destructive"):
            from core import confirm
            confirm.set_pending("shell", cmd, cmd)
            return (f"⚠️ CONFIRM NEEDED — this command is destructive:\n`{cmd}`\n"
                    "Reply 'yes' to run it or 'no' to cancel.")
    try:
        if IS_WIN:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                capture_output=True, text=True, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            r = subprocess.run(["bash", "-c", cmd], capture_output=True,
                               text=True, timeout=timeout)
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        parts = []
        if out: parts.append(out[:3000])
        if err: parts.append(f"stderr: {err[:1000]}")
        if not parts: parts.append("(no output)")
        if r.returncode != 0: parts.append(f"(exit code {r.returncode})")
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        return f"⏱️ Timed out after {timeout}s: {cmd}"
    except Exception as e:
        return f"Shell error: {e}"


def get_os_tool_description():
    return """
[OS: open | app]         → Open app (chrome/vscode/terminal/calculator...)
[OS: type | text]        → Type into active window
[OS: press | ctrl+c]     → Press key combo
[OS: volume | 70]        → Set volume 0-100
[OS: kill | process]     → Kill process
[OS: url | https://...]  → Open URL in browser
[OS: processes]          → List running processes
[OS: active_window]      → Get active window title
[SHELL: command]         → Run a terminal command (PowerShell) and get its output,
                           e.g. [SHELL: Get-Date] or [SHELL: ipconfig]
[CODEEDIT: repo | change]→ Edit code in a project folder (reliable multi-file edits
                           via the configured backend — Aider or Claude Code). e.g.
                           [CODEEDIT: C:\\proj | add a --verbose flag to main.py]
[DELEGATE: task]         → Hand a big multi-step job to the autonomous Claude Code
                           agent (builds whole projects, creates & edits many files,
                           iterates). Use for "build me an app that…" type requests.
                           Optionally [DELEGATE: C:\\folder | task] to set the workdir.
"""
