"""
Assistant Engine — clean class-based design, no monkey-patching.
Routes: simple queries → direct path, complex → agent loop.
Integrates: memory, summariser, model router, RAG, plugins, all tools.
"""

import re
import json
import requests
import uuid
from datetime import datetime
from typing import List, Dict, Callable, Optional, Tuple

from core.logger import get_logger
from core.memory import (
    init_db, get_or_create_session, log_message,
    get_session_messages, get_facts_for_prompt,
    get_episodic_summary_for_prompt, extract_and_save_facts
)
from core.tools import web_search, run_code, get_clipboard, take_screenshot, TOOL_DESCRIPTIONS
from core.file_ops import read_file, write_file, find_files, get_file_tool_description
from core.os_control import execute_os_command, get_os_tool_description
from core.summariser import maybe_summarise, inject_summary_if_exists
from core.world_model import (
    init_world_model, get_world_model_for_prompt, update_from_conversation
)
from core.emotional_state import (
    init_emotional_state, update_state, get_emotional_prompt_hint
)
from core import environment as env
from core import mcp_client as mcp
import config as cfg

log = get_logger("assistant")

# ── Tag patterns ───────────────────────────────────────────────────────────────
_PATTERNS = {
    "search":     re.compile(r'\[\s*SEARCH:\s*(.+?)\s*\]',   re.I | re.S),
    "code":       re.compile(r'\[\s*CODE:\s*(.+?)\s*\]',     re.I | re.S),
    "clipboard":  re.compile(r'\[\s*CLIPBOARD\s*\]',          re.I),
    "screenshot": re.compile(r'\[\s*SCREENSHOT\s*\]',         re.I),
    "file":       re.compile(r'\[\s*FILE:\s*(.+?)\s*\]',     re.I | re.S),
    # WRITE is greedy to the LAST ']' — file content may itself contain brackets
    "write":      re.compile(r'\[\s*WRITE:\s*(.+)\s*\]',     re.I | re.S),
    "find":       re.compile(r'\[\s*FIND:\s*(.+?)\s*\]',     re.I | re.S),
    "os":         re.compile(r'\[\s*OS:\s*(.+?)\s*\]',       re.I | re.S),
    # SHELL is greedy to the LAST ']' — PowerShell commands often contain ']'
    "shell":      re.compile(r'\[\s*SHELL:\s*(.+)\s*\]',     re.I | re.S),
    "aider":      re.compile(r'\[\s*AIDER:\s*(.+)\s*\]',     re.I | re.S),
    "codeedit":   re.compile(r'\[\s*CODEEDIT:\s*(.+)\s*\]',  re.I | re.S),
    "delegate":   re.compile(r'\[\s*DELEGATE:\s*(.+)\s*\]',  re.I | re.S),
    "email":      re.compile(r'\[\s*EMAIL:\s*(.+?)\s*\]',    re.I | re.S),
    "rag":        re.compile(r'\[\s*RAG:\s*(.+?)\s*\]',      re.I | re.S),
    "reminders":  re.compile(r'\[\s*REMINDERS\s*:?\s*([^\]]*)\]', re.I),
    "remember":   re.compile(r'\[\s*REMEMBER:\s*(.+?)\s*\]', re.I | re.S),
    "reminder":   re.compile(r'\[\s*REMINDER:\s*(.+?)\s*\]', re.I | re.S),
    "fact":       re.compile(r'\[FACT:[^\]]*\]',        re.I),
}

AGENT_TRIGGERS = [
    "then", "after that", "and then", "followed by",
    "step by step", "search and", "find and", "open and",
    "write a script", "save to", "look at my screen and",
    "autonomously", "automatically", "chain", "pipeline",
]

SIMPLE_PREFIXES = [
    "what is", "what's", "who is", "when", "where",
    "how much", "how many", "define", "remind me", "remember",
]


def _detect_tool(text: str) -> Optional[Tuple[str, str]]:
    """Detect the first tool tag in text. Returns (tool_name, arg) or None."""
    for name, pattern in _PATTERNS.items():
        if name in ("fact", "reminder", "remember"):
            continue
        m = pattern.search(text)
        if m:
            arg = m.group(1).strip() if m.lastindex else ""
            return (name, arg)
    return None


def _execute_tool(tool: str, arg: str, rag=None, plugin_manager=None,
                  reminder_engine=None) -> Tuple[str, Optional[str]]:
    """Execute a tool. Returns (result_text, image_b64_or_None)."""
    if tool == "search":
        return web_search(arg), None
    elif tool == "code":
        return run_code(arg), None
    elif tool == "clipboard":
        return get_clipboard(), None
    elif tool == "screenshot":
        b64, desc = take_screenshot()
        return desc, b64 or None
    elif tool == "file":
        content, _ = read_file(arg.split("|")[0].strip())
        return content, None
    elif tool == "write":
        parts = arg.split("|", 1)
        if len(parts) < 2:
            return "WRITE needs: [WRITE: path | full file content]", None
        return write_file(parts[0], parts[1].strip()), None
    elif tool == "find":
        parts = arg.split("|", 1)
        return find_files(parts[0], parts[1] if len(parts) > 1 else None), None
    elif tool == "os":
        parts = arg.split("|", 1)
        return execute_os_command(parts[0].strip(),
                                  parts[1].strip() if len(parts) > 1 else ""), None
    elif tool == "shell":
        from core.os_control import run_shell
        return run_shell(arg), None
    elif tool == "email":
        from core.email_client import handle as handle_email
        return handle_email(arg), None
    elif tool == "aider":
        from core.aider_integration import run_aider
        return run_aider(arg), None
    elif tool == "codeedit":
        from core.code_edit import run as run_code_edit
        return run_code_edit(arg), None
    elif tool == "delegate":
        from core.claude_code_integration import run_agent
        parts = arg.split("|", 1)
        if len(parts) == 2 and ("\\" in parts[0] or "/" in parts[0]):
            return run_agent(parts[1].strip(), workdir=parts[0].strip()), None
        return run_agent(arg), None
    elif tool == "rag":
        if rag:
            results = rag.search(arg)
            return rag.format_results(results), None
        return "RAG engine not initialised.", None
    elif tool == "reminders":
        from core.reminders import manage as manage_reminders
        return manage_reminders(arg, engine=reminder_engine), None
    return f"Unknown tool: {tool}", None


_HARMFUL_HINTS = (
    "kill", "malware", "ransomware", "exploit", "steal", "hack into",
    "ddos", "keylogger", "phishing", "make a bomb", "hurt", "weapon",
)


def _looks_harmful(message: str) -> bool:
    msg = message.lower()
    return any(h in msg for h in _HARMFUL_HINTS)


def _tool_failed(result_text: str) -> bool:
    head = (result_text or "").strip().lower()[:80]
    return any(m in head for m in ("error", "failed", "not initialised",
                                   "not found", "unable to", "exception", "traceback"))


_HARD_HINTS = (
    "prove", "derive", "analyse", "analyze", "architecture", "design a",
    "optimize", "optimise", "algorithm", "in detail", "step by step",
    "why does", "trade-off", "tradeoff", "complexity", "refactor",
    "theorem", "mathematically", "explain how", "debug this", "reasoning",
)


def _is_hard_query(message: str) -> bool:
    """Very difficult query → route to Claude (when a key is configured)."""
    if len(message.split()) > 60:
        return True
    m = message.lower()
    return any(h in m for h in _HARD_HINTS)


def _should_use_agent(message: str) -> bool:
    msg = message.lower()
    if any(msg.startswith(p) for p in SIMPLE_PREFIXES):
        return False
    if any(t in msg for t in AGENT_TRIGGERS):
        return True
    if len(message.split()) > 25:
        return True
    return False


class Assistant:
    def __init__(self, on_reminder: Optional[Callable] = None):
        init_db()
        init_world_model()
        init_emotional_state()
        try:
            from core.knowledge_graph import init_kg
            init_kg()
        except Exception as e:
            log.warning(f"KG init failed: {e}")
        env.prime_async()
        self.session_id       = str(uuid.uuid4())
        self.on_reminder      = on_reminder
        self._reminder_engine = None
        self._rag             = None       # injected from main.py
        self._plugin_manager  = None       # injected from main.py
        self._msg_count       = 0

        get_or_create_session(self.session_id)
        self._check_ollama()
        self._init_reminders()

    def _check_ollama(self):
        try:
            r = requests.get(f"{cfg.get('ollama_base_url')}/api/tags", timeout=4)
            r.raise_for_status()
        except Exception:
            raise RuntimeError(
                f"Ollama not running.\n"
                f"  1. ollama serve\n"
                f"  2. ollama pull {cfg.get('ollama_model')}\n"
                f"  3. ollama pull nomic-embed-text  (for RAG)"
            )

    def _init_reminders(self):
        try:
            from core.reminders import ReminderEngine
            self._reminder_engine = ReminderEngine(
                on_reminder=self.on_reminder or (lambda t: log.info(f"Reminder: {t}"))
            )
        except Exception as e:
            log.warning(f"Reminder engine failed: {e}")

    def _build_system_prompt(self, user_message: str = "") -> str:
        facts    = get_facts_for_prompt()
        episodic = get_episodic_summary_for_prompt(days_back=cfg.get("episodic_days"))
        name     = cfg.get("assistant_name")
        user     = cfg.get("user_name")

        parts = [
            f"You are {name}, a smart, warm, autonomous AI assistant for {user}.",
            "You have persistent memory, multi-step tools, file access, and OS control.",
            "",
            "MEMORY RULES:",
            "- Tag new personal facts as [FACT: short description].",
            "- Never forget known user info.",
            "- Use history below for past conversation questions.",
            "",
        ]
        if facts:    parts += [facts, ""]
        if episodic: parts += [episodic, ""]

        world = get_world_model_for_prompt()
        if world: parts += [world, ""]

        try:
            from core.knowledge_graph import (graph_for_prompt,
                                               relevant_for_prompt, stats)
            ne, _ = stats()
            # Small graph → include it all; large → only entities relevant now.
            kg = ""
            if user_message and ne > 12:
                kg = relevant_for_prompt(user_message)
            if not kg:
                kg = graph_for_prompt()
            if kg: parts += [kg, ""]
        except Exception:
            pass

        mood = get_emotional_prompt_hint()
        if mood: parts += [mood, ""]

        # Active reminders — so "what are my reminders?" works across restarts
        # and the model doesn't re-create ones that already exist.
        try:
            from core.reminders import get_all_reminders
            rows = get_all_reminders()
            if rows:
                parts.append("ACTIVE REMINDERS (already scheduled — answer from "
                             "this list when asked; do NOT create duplicates):")
                for r in rows:
                    parts.append(f"- {r['remind_at']} ({r['recurrence']}): {r['title']}")
                parts.append("")
        except Exception:
            pass

        parts += [env.get_environment_for_prompt(), ""]

        parts.append(TOOL_DESCRIPTIONS)
        parts.append(get_file_tool_description())
        parts.append(get_os_tool_description())

        try:
            from core.email_client import configured as email_ok
            if email_ok():
                parts.append(
                    "\n[EMAIL: unread]                → List unread emails"
                    "\n[EMAIL: inbox]                 → List recent inbox emails"
                    "\n[EMAIL: search | gmail-query]  → Filter emails, e.g. "
                    "[EMAIL: search | from:boss is:unread] or [EMAIL: search | "
                    "subject:invoice after:2026/01/01]"
                    "\n[EMAIL: read | number]         → Read one email in full"
                    "\n[EMAIL: send | to | subject | body] → Send an email (the user "
                    "is asked to confirm before it actually sends)\n")
        except Exception:
            pass

        # RAG status
        if self._rag:
            parts.append(self._rag.get_rag_tool_description())

        # Plugin tools
        if self._plugin_manager:
            desc = self._plugin_manager.get_tool_descriptions()
            if desc:
                parts.append(desc)

        # MCP connector tools
        mcp_desc = mcp.get_tool_descriptions()
        if mcp_desc:
            parts.append(mcp_desc)

        parts += [
            "",
            "TOOL EXAMPLES — when a task needs a tool, output the tag ALONE "
            "(no explanation, no invented results):",
            'User: "increase the volume to 90"    → [OS: volume | 90]',
            'User: "what is my local IP?"         → [SHELL: ipconfig]',
            'User: "open chrome"                  → [OS: open | chrome]',
            'User: "find my resume on this pc"    → [FIND: resume]',
            'User: "create notes.txt saying hi"   → [WRITE: notes.txt | hi]',
            'User: "weather in Paris?"            → [SEARCH: current weather Paris]',
            'User: "remember my birthday is in March" → [REMEMBER: Hritick | birthday is in March]',
            'User: "mark call mummy as done"      → [REMINDERS: done | call mummy]',
            'User: "cancel my gym reminder"       → [REMINDERS: delete | gym]',
            "",
            "BEHAVIOUR:",
            f"- Be concise. Address {user} by name occasionally.",
            "- You HAVE full computer control through the tags above — never say "
            "you lack the capability.",
            "- Emit exactly ONE tag, then STOP. The tool runs and its real result "
            "comes back to you; only then answer the user.",
            "- Never fabricate a tool result.",
            "- Confirm reminders and OS actions clearly.",
        ]
        return "\n".join(parts)

    def _get_context(self) -> List[Dict]:
        msgs = get_session_messages(self.session_id)
        msgs = inject_summary_if_exists(self.session_id, msgs)
        msgs = maybe_summarise(self.session_id, msgs)
        return msgs[-cfg.get("context_window"):]

    def _get_model(self, message: str) -> str:
        """Route to best available model for this query."""
        try:
            from core.model_router import route
            return route(message)
        except Exception:
            return cfg.get("ollama_model")

    def chat(
        self,
        user_message: str,
        on_token:      Optional[Callable] = None,
        on_tool_start: Optional[Callable] = None,
        on_tool_done:  Optional[Callable] = None,
        on_agent_step: Optional[Callable] = None,
        on_image:      Optional[Callable] = None,
    ) -> str:
        log.info(f"User: {user_message[:80]}")
        log_message(self.session_id, "user", user_message)

        # Pending destructive-action confirmation takes priority over anything.
        from core import confirm
        if confirm.has_pending():
            verdict = confirm.classify(user_message)
            if verdict == "yes":
                if on_tool_start: on_tool_start("⚙️ Running confirmed action")
                result = confirm.execute_pending()
                if on_tool_done: on_tool_done(result)
                msg = f"Done — I ran it.\n\n{result[:600]}"
                if on_token: on_token(msg)
                return self._finalise(msg, user_message)
            confirm.clear()
            if verdict == "no":
                msg = "Cancelled — I didn't run it."
                if on_token: on_token(msg)
                return self._finalise(msg, user_message)
            # anything else: treat the parked action as abandoned and continue

        self._msg_count += 1
        self._emit("message")
        if _looks_harmful(user_message):
            self._emit("harmful_request")
        if self._msg_count and self._msg_count % 20 == 0:
            self._emit("long_session")

        # Handle index command for RAG
        index_match = re.search(
            r'index\s+(?:my\s+)?(?:documents?|files?|folder|directory)[\s:]+([^\s].+)',
            user_message, re.IGNORECASE
        )
        if index_match and self._rag:
            path = index_match.group(1).strip().strip('"\'')
            return self._handle_index(path, on_token)

        system  = self._build_system_prompt(user_message)
        history = self._get_context()
        model   = self._get_model(user_message)

        # Agent loop for complex queries
        if _should_use_agent(user_message):
            log.info("→ Agent loop")
            from core.agent import AgentLoop
            def _step(thought, action, result):
                self._emit("tool_failure" if _tool_failed(result) else "tool_success")
                if on_tool_start: on_tool_start(action)
                if on_tool_done:  on_tool_done(result)
                if on_agent_step: on_agent_step(thought, action, result)
            agent  = AgentLoop(system, on_step=_step, rag=self._rag)
            reply  = agent.run(user_message, history, on_token=on_token, model=model)
            return self._finalise(reply, user_message)

        # Direct path
        hard  = _is_hard_query(user_message)
        first = self._call_ollama(system, history, on_token, model=model, hard=hard)

        # Handle explicit REMEMBER tags (record into the knowledge graph)
        try:
            from core.knowledge_graph import remember
            for m in _PATTERNS["remember"].finditer(first):
                remember(m.group(1))
        except Exception as e:
            log.warning(f"Remember failed: {e}")

        # Handle reminder tag
        rm = _PATTERNS["reminder"].search(first)
        if rm and self._reminder_engine:
            from core.reminders import parse_reminder_tag
            reminder = parse_reminder_tag(first)
            if reminder:
                try:
                    self._reminder_engine.add(
                        reminder["title"], reminder["remind_at"], reminder["recurrence"]
                    )
                except Exception as e:
                    log.error(f"Reminder failed: {e}")

        # Tool loop: keep executing tool calls (plugin / MCP / built-in) until
        # the model answers without one, up to 3 rounds — so "let me try
        # again" actually tries again instead of dead-ending.
        reply = first
        for _ in range(3):
            hit = self._detect_any_tool(reply, on_tool_start)
            if not hit:
                break
            label, result, img_b64 = hit
            if on_tool_done: on_tool_done(result)
            if img_b64 and on_image: on_image(img_b64)
            self._emit("tool_failure" if _tool_failed(result) else "tool_success")
            history = history + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content":
                 f"Tool result:\n{result}\n\nAnswer the user's question directly "
                 f"using this result. Only use another tool if strictly necessary."}
            ]
            reply = self._call_ollama(system, history, on_token, model=model,
                                      image_b64=img_b64)
        return self._finalise(reply, user_message)

    def _detect_any_tool(self, text: str, on_tool_start=None
                         ) -> Optional[Tuple[str, str, Optional[str]]]:
        """Find the first plugin / MCP / built-in tool call in model output and
        run it. Returns (label, result_text, image_b64) or None."""
        tool = _detect_tool(text)
        if tool:
            tool_name, tool_arg = tool
            label = {
                "search":     f"🔍 Searching: {tool_arg[:45]}",
                "code":       "🐍 Running code",
                "clipboard":  "📋 Reading clipboard",
                "screenshot": "🖥️ Capturing screen",
                "file":       f"📄 Reading: {tool_arg[:40]}",
                "write":      f"📝 Writing: {tool_arg.split('|')[0].strip()[:40]}",
                "find":       f"🔎 Finding files: {tool_arg[:40]}",
                "os":         f"🖥️ OS: {tool_arg[:40]}",
                "shell":      f"💻 Terminal: {tool_arg[:45]}",
                "email":      f"📧 Email: {tool_arg[:40]}",
                "aider":      f"🛠 Aider editing: {tool_arg.split('|')[0].strip()[:35]}",
                "codeedit":   f"🛠 Editing code: {tool_arg.split('|')[0].strip()[:35]}",
                "delegate":   f"🤖 Agent working: {tool_arg[:40]}",
                "rag":        f"📚 Searching docs: {tool_arg[:40]}",
                "reminders":  f"🔔 Reminders: {tool_arg[:40] or 'list'}",
            }.get(tool_name, "🔧 Working")
            if on_tool_start: on_tool_start(label)
            result_text, img_b64 = _execute_tool(
                tool_name, tool_arg, rag=self._rag,
                plugin_manager=self._plugin_manager,
                reminder_engine=self._reminder_engine
            )
            log.info(f"Tool '{tool_name}': {result_text[:100]}")
            return label, result_text, img_b64

        # Plugins / MCP combine detect+execute, so the start callback
        # necessarily fires just before we return the finished result.
        if self._plugin_manager:
            hit = self._plugin_manager.detect_and_execute(text)
            if hit:
                plugin_name, result = hit
                label = f"🔌 Plugin: {plugin_name}"
                if on_tool_start: on_tool_start(label)
                return label, result, None

        mcp_hit = mcp.detect_and_execute(text)
        if mcp_hit:
            tool_label, result = mcp_hit
            label = f"🔌 Connector: {tool_label}"
            if on_tool_start: on_tool_start(label)
            return label, result, None

        return None

    def _handle_index(self, path: str, on_token) -> str:
        import threading
        if on_token: on_token(f"📂 Indexing {path} in the background...")
        def do():
            files, chunks = self._rag.index_directory(path)
            msg = f"✅ Indexed {files} files, {chunks} chunks from: {path}"
            log.info(msg)
        threading.Thread(target=do, daemon=True).start()
        reply = f"Started indexing `{path}`. I'll let you know when done."
        log_message(self.session_id, "assistant", reply)
        return reply

    def _finalise(self, reply: str, user_message: str) -> str:
        clean = _PATTERNS["fact"].sub("", reply).strip()
        clean = _PATTERNS["reminder"].sub("", clean).strip()
        clean = _PATTERNS["remember"].sub("", clean).strip()
        log_message(self.session_id, "assistant", clean)
        extract_and_save_facts(reply, user_message)
        self._update_world_model(user_message, clean)
        log.info(f"Assistant: {clean[:80]}")
        return clean

    def _emit(self, event_type: str):
        try:
            update_state(event_type)
        except Exception as e:
            log.warning(f"Emotional update '{event_type}' failed: {e}")

    def _update_world_model(self, user_message: str, reply: str):
        import threading
        def do():
            try:
                update_from_conversation(user_message, reply)
            except Exception as e:
                log.warning(f"World model update failed: {e}")
        threading.Thread(target=do, daemon=True).start()
        try:
            from core.knowledge_graph import extract_async
            extract_async(user_message, reply)
        except Exception as e:
            log.warning(f"KG extract dispatch failed: {e}")

    def _call_ollama(self, system, messages, on_token, model=None,
                     image_b64=None, hard=False) -> str:
        from core.llm_providers import complete
        return complete(system, messages, on_token=on_token, model=model,
                        image_b64=image_b64, temperature=0.7, hard=hard)
