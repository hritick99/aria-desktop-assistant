"""
Agent Loop — multi-turn tool chaining.
Accepts rag and plugin_manager as optional dependencies.
"""

import re
import json
import requests
from typing import List, Dict, Callable, Optional, Tuple
from core.logger import get_logger
import config as cfg

log = get_logger("agent")

MAX_STEPS     = 6
AGENT_TIMEOUT = 180

_PATTERNS = {
    "search":     re.compile(r'\[\s*SEARCH:\s*(.+?)\s*\]',   re.I | re.S),
    "code":       re.compile(r'\[\s*CODE:\s*(.+?)\s*\]',     re.I | re.S),
    "clipboard":  re.compile(r'\[\s*CLIPBOARD\s*\]',          re.I),
    "screenshot": re.compile(r'\[\s*SCREENSHOT\s*\]',         re.I),
    "file":       re.compile(r'\[\s*FILE:\s*(.+?)\s*\]',     re.I | re.S),
    "write":      re.compile(r'\[\s*WRITE:\s*(.+)\s*\]',     re.I | re.S),
    "find":       re.compile(r'\[\s*FIND:\s*(.+?)\s*\]',     re.I | re.S),
    "os":         re.compile(r'\[\s*OS:\s*(.+?)\s*\]',       re.I | re.S),
    "shell":      re.compile(r'\[\s*SHELL:\s*(.+)\s*\]',     re.I | re.S),
    "aider":      re.compile(r'\[\s*AIDER:\s*(.+)\s*\]',     re.I | re.S),
    "codeedit":   re.compile(r'\[\s*CODEEDIT:\s*(.+)\s*\]',  re.I | re.S),
    "delegate":   re.compile(r'\[\s*DELEGATE:\s*(.+)\s*\]',  re.I | re.S),
    "email":      re.compile(r'\[\s*EMAIL:\s*(.+?)\s*\]',    re.I | re.S),
    "rag":        re.compile(r'\[\s*RAG:\s*(.+?)\s*\]',      re.I | re.S),
    "reminders":  re.compile(r'\[\s*REMINDERS\s*:?\s*([^\]]*)\]', re.I),
    "done":       re.compile(r'\[\s*DONE\s*\]',               re.I),
}

AGENT_SYSTEM = """You are an autonomous agent solving tasks step by step.

For each step respond with:
Thought: <what and why>
Action: <tool tag OR [DONE]>

Available tools:
[SEARCH: query] [CODE: python] [CLIPBOARD] [SCREENSHOT]
[FILE: /path] [WRITE: path | content] [FIND: name or *.ext]
[OS: action | args] [SHELL: command] [RAG: query] [DONE]

Rules:
- One tool per step.
- Use [DONE] when ready to give the final answer.
- After [DONE], write your complete final answer.
- Max {max_steps} steps. Never repeat the same tool+arg.
"""


def _detect(text: str) -> Optional[Tuple[str, str]]:
    for name, pat in _PATTERNS.items():
        if name == "done": continue
        m = pat.search(text)
        if m:
            return (name, m.group(1).strip() if m.lastindex else "")
    return None


def _execute(tool: str, arg: str, rag=None) -> Tuple[str, Optional[str]]:
    from core.tools import web_search, run_code, get_clipboard, take_screenshot
    from core.file_ops import read_file, write_file, find_files
    from core.os_control import execute_os_command

    if tool == "search":   return web_search(arg), None
    if tool == "code":     return run_code(arg), None
    if tool == "clipboard": return get_clipboard(), None
    if tool == "screenshot":
        b64, desc = take_screenshot()
        return desc, b64 or None
    if tool == "file":
        content, _ = read_file(arg.split("|")[0].strip())
        return content, None
    if tool == "write":
        parts = arg.split("|", 1)
        if len(parts) < 2:
            return "WRITE needs: [WRITE: path | full file content]", None
        return write_file(parts[0], parts[1].strip()), None
    if tool == "find":
        parts = arg.split("|", 1)
        return find_files(parts[0], parts[1] if len(parts) > 1 else None), None
    if tool == "os":
        parts = arg.split("|", 1)
        return execute_os_command(parts[0].strip(),
                                  parts[1].strip() if len(parts) > 1 else ""), None
    if tool == "shell":
        from core.os_control import run_shell
        return run_shell(arg), None
    if tool == "rag":
        if rag:
            results = rag.search(arg)
            return rag.format_results(results), None
        return "RAG not available.", None
    if tool == "reminders":
        from core.reminders import manage
        return manage(arg), None
    if tool == "aider":
        from core.aider_integration import run_aider
        return run_aider(arg), None
    if tool == "codeedit":
        from core.code_edit import run as run_code_edit
        return run_code_edit(arg), None
    if tool == "delegate":
        from core.claude_code_integration import run_agent
        return run_agent(arg), None
    if tool == "email":
        from core.email_client import handle as handle_email
        return handle_email(arg), None
    return f"Unknown tool: {tool}", None


class AgentLoop:
    def __init__(self, system_prefix: str = "", on_step=None, rag=None):
        self.system_prefix = system_prefix
        self.on_step       = on_step
        self.rag           = rag

    def run(self, user_message: str, history: List[Dict],
            on_token=None, model: str = None) -> str:
        system   = self.system_prefix + "\n\n" + AGENT_SYSTEM.format(max_steps=MAX_STEPS)
        messages = list(history) + [{"role": "user", "content": user_message}]
        steps    = []
        img_b64  = None
        final    = ""
        model    = model or cfg.get("ollama_model")

        for i in range(MAX_STEPS):
            log.info(f"Agent step {i+1}")
            ctx = list(messages)
            if steps:
                ctx.append({"role": "user",
                             "content": "Previous steps:\n" +
                             "\n".join(f"Step {j+1}: {r}" for j, r in enumerate(steps)) +
                             "\n\nContinue."})

            reply  = self._call(system, ctx, img_b64, model, on_token)
            img_b64 = None

            if _PATTERNS["done"].search(reply):
                parts = re.split(r'\[DONE\]', reply, flags=re.I)
                final = parts[-1].strip() if len(parts) > 1 else reply.replace("[DONE]", "").strip()
                break

            tool = _detect(reply)
            if not tool:
                final = reply
                break

            tool_name, tool_arg = tool
            label = f"🔧 {tool_name}: {tool_arg[:40]}"
            thought = ""
            tm = re.search(r'Thought:\s*(.+?)(?:\nAction:|$)', reply, re.S)
            if tm: thought = tm.group(1).strip()[:100]

            result, img = _execute(tool_name, tool_arg, rag=self.rag)
            if img: img_b64 = img
            steps.append(f"[{label}]\n{result[:500]}")

            if self.on_step: self.on_step(thought, label, result[:200])

        if not final:
            # Synthesise from steps
            ctx = list(messages) + [
                {"role": "user",
                 "content": "Steps:\n" + "\n".join(steps) +
                 "\n\nGive the final complete answer now."}
            ]
            final = self._call(system, ctx, None, model, on_token)

        return final

    def _call(self, system, messages, img_b64, model, on_token) -> str:
        from core.llm_providers import complete
        return complete(system, messages, on_token=on_token, model=model,
                        image_b64=img_b64, temperature=0.4, hard=False)
