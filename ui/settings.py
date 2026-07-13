"""Settings panel — live config editing (Claude-style theme)."""
import threading
import customtkinter as ctk
import config as cfg
from core.logger import get_logger
from ui.theme import C, FONT, SERIF

log = get_logger("settings")


class SettingsPanel(ctk.CTkToplevel):
    def __init__(self, parent, on_apply=None, tts_engine=None, hotkey_listener=None):
        super().__init__(parent)
        self.on_apply = on_apply; self.tts = tts_engine; self.hotkey = hotkey_listener
        self.title("Settings"); self.geometry("520x720")
        self.configure(fg_color=C["bg"]); self.resizable(False, True)
        self.attributes("-topmost", True)
        self._custom_rows = []   # [(name_e, url_e, key_e, model_e, frame)]
        self._mcp_rows    = []   # [(name_e, cmd_e, enabled_var, frame)]
        self._build()

    # ── small builders ──────────────────────────────────────────────────────
    def _section(self, label):
        ctk.CTkLabel(self._scroll, text=label, font=(SERIF,13,"bold"),
                     text_color=C["accent"]).pack(anchor="w", padx=6, pady=(18,4))

    def _hint(self, text):
        ctk.CTkLabel(self._scroll, text=text, font=(FONT,10), text_color=C["muted"],
                     anchor="w", justify="left", wraplength=460).pack(anchor="w", padx=6, pady=(0,4))

    def _row(self, label, factory):
        f = ctk.CTkFrame(self._scroll, fg_color=C["panel"], corner_radius=10)
        f.pack(fill="x", padx=2, pady=3)
        ctk.CTkLabel(f, text=label, font=(FONT,12), text_color=C["text"],
                     width=150, anchor="w").pack(side="left", padx=12, pady=10)
        w = factory(f); w.pack(side="right", padx=12, pady=8); return w

    def _entry(self, parent, value, width=200, show=None, placeholder=None):
        e = ctk.CTkEntry(parent, width=width, height=30, fg_color=C["input"], show=show,
                         border_color=C["border"], text_color=C["text"], font=(FONT,11),
                         placeholder_text=placeholder or "", placeholder_text_color=C["muted"])
        if value: e.insert(0, str(value))
        return e

    def _dropdown(self, parent, variable, values, width=160):
        return ctk.CTkOptionMenu(parent, variable=variable, values=values,
                                 width=width, height=30, fg_color=C["input"],
                                 button_color=C["accent"], button_hover_color=C["accent2"],
                                 dropdown_fg_color=C["panel"], font=(FONT,11))

    def _small_btn(self, parent, text, cmd, width=110):
        return ctk.CTkButton(parent, text=text, height=28, width=width,
                             fg_color=C["panel2"], hover_color=C["accent_s"],
                             font=(FONT,11), text_color=C["dim"], corner_radius=14,
                             command=cmd)

    def _test_llm(self, kind, get_params, label):
        """Run a connectivity test with the values currently typed in the form."""
        self._status.configure(text=f"Testing {label}…", text_color=C["dim"])
        params = get_params()
        def do():
            from core.llm_providers import test_connection
            ok, msg = test_connection(kind, **params)
            try:
                self.after(0, lambda: self._status.configure(
                    text=f"{label}: {msg}",
                    text_color=C["green"] if ok else C["red"]))
            except Exception:
                pass
        threading.Thread(target=do, daemon=True).start()

    # ── layout ──────────────────────────────────────────────────────────────
    def _build(self):
        ctk.CTkLabel(self, text="Settings", font=(SERIF,18,"bold"),
                     text_color=C["text"]).pack(pady=(18,2))
        ctk.CTkLabel(self, text="Apply & Save writes changes instantly", font=(FONT,10),
                     text_color=C["muted"]).pack(pady=(0,8))

        self._scroll = ctk.CTkScrollableFrame(self, fg_color=C["bg"], corner_radius=0)
        self._scroll.pack(fill="both", expand=True, padx=14, pady=(0,4))

        # ── Providers ──
        self._section("Model Providers")
        self._hint("Pick which brain answers. 'auto' = Groq for speed, Claude for hard "
                   "questions, local Ollama as fallback. 'claude_code' = your Claude "
                   "Pro subscription via the Claude Code CLI (no API tokens — needs "
                   "Claude Code installed + a one-time `claude` login; slower, and "
                   "subject to your plan's usage limits). Add any OpenAI-compatible "
                   "LLM below.")
        self._bvar = ctk.StringVar(value=cfg.get("llm_backend"))
        self._backend_menu = self._row("Backend", lambda p: self._dropdown(
            p, self._bvar, self._backend_values()))
        self._groq_k = self._row("Groq API key",  lambda p: self._entry(p, cfg.get("groq_api_key"), show="•"))
        self._groq_m = self._row("Groq model",     lambda p: self._entry(p, cfg.get("groq_model")))
        self._cl_k   = self._row("Claude API key", lambda p: self._entry(p, cfg.get("claude_api_key"), show="•"))
        self._cl_m   = self._row("Claude model",   lambda p: self._entry(p, cfg.get("claude_model")))
        tb = ctk.CTkFrame(self._scroll, fg_color="transparent")
        tb.pack(anchor="w", padx=4, pady=(4,0))
        self._small_btn(tb, "Test Groq", lambda: self._test_llm(
            "openai_compat", lambda: {
                "base_url": cfg.get("groq_base_url") or "https://api.groq.com/openai/v1",
                "api_key":  self._groq_k.get().strip(),
                "model":    self._groq_m.get().strip()}, "Groq")).pack(side="left", padx=(0,6))
        self._small_btn(tb, "Test Claude", lambda: self._test_llm(
            "claude", lambda: {
                "api_key": self._cl_k.get().strip(),
                "model":   self._cl_m.get().strip()}, "Claude")).pack(side="left")

        ctk.CTkLabel(self._scroll, text="Custom providers", font=(FONT,11,"bold"),
                     text_color=C["dim"]).pack(anchor="w", padx=6, pady=(10,2))
        self._custom_box = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._custom_box.pack(fill="x")
        for p in (cfg.get("custom_llms") or []):
            self._add_custom_row(p)
        ctk.CTkButton(self._scroll, text="+  Add provider", height=30, width=140,
                      fg_color=C["panel2"], hover_color=C["accent_s"], font=(FONT,11),
                      text_color=C["dim"], corner_radius=15,
                      command=self._add_custom_row).pack(anchor="w", padx=4, pady=(2,0))

        # ── Ollama ──
        self._section("Local Models (Ollama)")
        installed = self._ollama_models()
        current = cfg.get("ollama_model")
        if current and current not in installed:
            installed.insert(0, current)
        self._model_cb = self._row("Model", lambda p: ctk.CTkComboBox(
            p, values=installed or [current], width=200, height=30,
            fg_color=C["input"], button_color=C["accent"], button_hover_color=C["accent2"],
            dropdown_fg_color=C["panel"], border_color=C["border"],
            text_color=C["text"], font=(FONT,11)))
        self._model_cb.set(current)
        self._url = self._row("Ollama URL",     lambda p: self._entry(p, cfg.get("ollama_base_url")))
        self._ctx = self._row("Context window", lambda p: self._entry(p, cfg.get("context_window"), 80))
        self._small_btn(self._scroll, "Test Ollama", lambda: self._test_llm(
            "ollama", lambda: {"base_url": self._url.get().strip()}, "Ollama")
            ).pack(anchor="w", padx=4, pady=(4,0))

        # ── Connectors ──
        self._section("Connectors (MCP)")
        self._hint("Connect the same MCP plugins Claude desktop uses. Command is what "
                   "launches the server, e.g.  npx -y @modelcontextprotocol/server-filesystem "
                   "C:\\Users\\you\\Documents   — restart or Apply to (re)connect.")
        # One-click catalog of common servers
        ctk.CTkLabel(self._scroll, text="Quick add (needs Node.js):", font=(FONT,10),
                     text_color=C["dim"], anchor="w").pack(anchor="w", padx=6, pady=(2,0))
        cat = ctk.CTkFrame(self._scroll, fg_color="transparent")
        cat.pack(fill="x", padx=2, pady=(0,4))
        for i, (label, preset) in enumerate(self._mcp_catalog()):
            ctk.CTkButton(cat, text=label, height=26, fg_color=C["panel2"],
                          hover_color=C["accent_s"], font=(FONT,10), text_color=C["dim"],
                          corner_radius=13,
                          command=lambda p=preset: self._add_preset(p)
                          ).grid(row=i//2, column=i % 2, padx=3, pady=3, sticky="ew")
        cat.grid_columnconfigure((0,1), weight=1)

        self._mcp_box = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._mcp_box.pack(fill="x")
        for s in (cfg.get("mcp_servers") or []):
            self._add_mcp_row(s)
        ctk.CTkButton(self._scroll, text="+  Add custom connector", height=30, width=170,
                      fg_color=C["panel2"], hover_color=C["accent_s"], font=(FONT,11),
                      text_color=C["dim"], corner_radius=15,
                      command=self._add_mcp_row).pack(anchor="w", padx=4, pady=(2,0))
        self._mcp_status = ctk.CTkLabel(self._scroll, text=self._mcp_status_text(),
                                        font=(FONT,10), text_color=C["muted"],
                                        anchor="w", justify="left")
        self._mcp_status.pack(anchor="w", padx=6, pady=(4,0))

        # ── Email (IMAP) ──
        self._section("Email (read & filter)")
        self._hint("Read and filter your inbox. For Gmail: turn on 2-step "
                   "verification, then create an App Password at "
                   "myaccount.google.com/apppasswords and paste it below (NOT your "
                   "normal password). Read-only — Aria can't delete or send.")
        self._em_addr = self._row("Email address", lambda p: self._entry(
            p, cfg.get("email_address"), placeholder="you@gmail.com"))
        self._em_pass = self._row("App password", lambda p: self._entry(
            p, cfg.get("email_app_password"), show="•", placeholder="16-char app password"))
        self._em_host = self._row("IMAP host", lambda p: self._entry(
            p, cfg.get("email_imap_host")))
        self._em_smtp = self._row("SMTP host (send)", lambda p: self._entry(
            p, cfg.get("email_smtp_host")))
        ctk.CTkButton(self._scroll, text="Test email login", height=30, width=150,
                      fg_color=C["panel2"], hover_color=C["accent_s"], font=(FONT,11),
                      text_color=C["dim"], corner_radius=15,
                      command=self._email_test).pack(anchor="w", padx=4, pady=(2,0))

        # ── Phone notifications ──
        self._section("Phone Notifications")
        self._hint("Push reminders to your phone via ntfy.sh (free, no account). "
                   "Install the ntfy app, enable this, Apply, then subscribe to the "
                   "topic shown below in the app. Keep the topic secret — anyone who "
                   "knows it can read your pushes.")
        self._ntfy_v = ctk.BooleanVar(value=cfg.get("ntfy_enabled"))
        self._row("Push to phone", lambda p: ctk.CTkSwitch(p, variable=self._ntfy_v, text="",
                                                            progress_color=C["accent"]))
        self._ntfy_t = self._row("Topic", lambda p: self._entry(
            p, cfg.get("ntfy_topic"), placeholder="auto-generated on Apply"))
        self._ntfy_s = self._row("Server", lambda p: self._entry(p, cfg.get("ntfy_server")))
        ctk.CTkButton(self._scroll, text="Send test notification", height=30, width=180,
                      fg_color=C["panel2"], hover_color=C["accent_s"], font=(FONT,11),
                      text_color=C["dim"], corner_radius=15,
                      command=self._ntfy_test).pack(anchor="w", padx=4, pady=(2,0))

        # ── Identity ──
        self._section("Identity")
        self._user = self._row("Your name",      lambda p: self._entry(p, cfg.get("user_name")))
        self._asst = self._row("Assistant name", lambda p: self._entry(p, cfg.get("assistant_name")))

        # ── Voice ──
        self._section("Voice & Speech")
        self._wvar = ctk.StringVar(value=cfg.get("whisper_model"))
        self._row("Whisper model", lambda p: self._dropdown(p, self._wvar, ["tiny","base","small"], 120))
        self._tts_v = ctk.BooleanVar(value=cfg.get("tts_enabled"))
        self._row("Enable TTS", lambda p: ctk.CTkSwitch(p, variable=self._tts_v, text="",
                                                         progress_color=C["accent"]))
        self._rate = self._row("Speech rate (wpm)", lambda p: self._entry(p, cfg.get("tts_rate"), 80))
        self._vol  = self._row("Volume (0-1)",      lambda p: self._entry(p, cfg.get("tts_volume"), 80))

        # ── Hotkey / wake ──
        self._section("Hotkey & Wake Word")
        self._hkey = self._row("Toggle hotkey", lambda p: self._entry(p, cfg.get("hotkey")))
        self._ww_v = ctk.BooleanVar(value=cfg.get("wake_word_enabled"))
        self._row("Wake word enabled", lambda p: ctk.CTkSwitch(p, variable=self._ww_v, text="",
                                                                progress_color=C["accent"]))
        self._ww = self._row("Wake word phrase", lambda p: self._entry(p, cfg.get("wake_word")))
        self._vad_v = ctk.BooleanVar(value=cfg.get("vad_enabled"))
        self._row("VAD auto-listen", lambda p: ctk.CTkSwitch(p, variable=self._vad_v, text="",
                                                              progress_color=C["accent"]))

        # ── Autonomy ──
        self._section("Autonomy")
        self._hint("Full computer control removes the safety guards: the terminal "
                   "blocklist (shutdown/format/registry deletes…), the system-folder "
                   "write guard, and the Python sandbox limits. Aria can then do "
                   "anything your user account can. Enable only if you trust that.")
        self._full_v = ctk.BooleanVar(value=cfg.get("full_control"))
        self._row("Full computer control", lambda p: ctk.CTkSwitch(
            p, variable=self._full_v, text="", progress_color=C["red"]))
        self._confirm_v = ctk.BooleanVar(value=cfg.get("confirm_destructive"))
        self._row("Ask before destructive actions", lambda p: ctk.CTkSwitch(
            p, variable=self._confirm_v, text="", progress_color=C["accent"]))
        self._hint("Recommended ON: even with full control, Aria asks 'yes/no' "
                   "in chat before shutdown, format, delete, registry edits, or "
                   "writing into system folders.")

        # ── Code editing (Aider / Claude Code) ──
        self._section("Code Editing")
        try:
            from core.aider_integration import available as _aider_ok
            aider_on = _aider_ok()
        except Exception:
            aider_on = False
        try:
            from core.claude_code_integration import available as _cc_ok
            cc_on = _cc_ok()
        except Exception:
            cc_on = False
        self._hint(
            f"Backend for code edits.  Aider: {'✓ installed' if aider_on else '✗ not installed (pip install aider-chat)'}"
            f"   ·   Claude Code: {'✓ installed' if cc_on else '✗ not installed'}.\n"
            "Aider uses your API key (per-token). Claude Code uses your Claude "
            "Pro/Max subscription (no API tokens) — needs Node.js + "
            "`npm install -g @anthropic-ai/claude-code` + a one-time `claude` login.")
        self._cb_var = ctk.StringVar(
            value="Claude Code" if cfg.get("code_backend") == "claude_code" else "Aider")
        self._row("Code backend", lambda p: self._dropdown(
            p, self._cb_var, ["Aider", "Claude Code"], 140))
        self._aider_m = self._row("Aider model", lambda p: self._entry(
            p, cfg.get("aider_model"), placeholder="auto (from your keys)"))

        # ── GitHub ──
        self._section("GitHub Plugin")
        self._gh_t = self._row("GitHub token",    lambda p: self._entry(p, cfg.get("github_token"), show="•"))
        self._gh_u = self._row("GitHub username", lambda p: self._entry(p, cfg.get("github_username")))

        # ── Appearance ──
        self._section("Appearance")
        self._opa = self._row("Opacity (0.7-1.0)", lambda p: self._entry(p, cfg.get("opacity"), 80))

        # ── footer ──
        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.pack(fill="x", padx=16, pady=(10,4))
        ctk.CTkButton(btn, text="Reset Defaults", width=120, height=34,
                      fg_color=C["panel2"], hover_color=C["red"],
                      font=(FONT,12), text_color=C["dim"], corner_radius=17,
                      command=self._reset).pack(side="left")
        ctk.CTkButton(btn, text="Apply & Save", width=140, height=34,
                      fg_color=C["accent"], hover_color=C["accent2"],
                      font=(FONT,12,"bold"), text_color=C["bg"], corner_radius=17,
                      command=self._apply).pack(side="right")
        self._status = ctk.CTkLabel(self, text="", font=(FONT,11), text_color=C["green"])
        self._status.pack(pady=(0,10))

    # ── dynamic rows ────────────────────────────────────────────────────────
    def _backend_values(self):
        names = [p.get("name","") for p in (cfg.get("custom_llms") or []) if p.get("name")]
        return ["auto","ollama","groq","claude","claude_code"] + names

    def _ollama_models(self):
        try:
            from core.llm_providers import list_ollama_models
            return list_ollama_models()
        except Exception:
            return []

    def _mcp_status_text(self):
        try:
            from core import mcp_client
            st = mcp_client.status()
            if not st:
                return "No connectors running."
            return "Running:  " + ",  ".join(
                f"{s['name']} ({s['tools']} tools)" for s in st if s["alive"])
        except Exception:
            return ""

    def _add_custom_row(self, data=None):
        data = data or {}
        f = ctk.CTkFrame(self._custom_box, fg_color=C["panel"], corner_radius=10)
        f.pack(fill="x", padx=2, pady=3)
        top = ctk.CTkFrame(f, fg_color="transparent"); top.pack(fill="x", padx=8, pady=(8,2))
        name_e = self._entry(top, data.get("name",""),  120, placeholder="Name")
        name_e.pack(side="left", padx=(0,4))
        url_e  = self._entry(top, data.get("base_url",""), 250, placeholder="https://api.openai.com/v1")
        url_e.pack(side="left", fill="x", expand=True, padx=(0,4))
        ctk.CTkButton(top, text="✕", width=26, height=26, fg_color="transparent",
                      hover_color=C["red"], text_color=C["muted"], font=(FONT,11),
                      command=lambda: self._remove_custom(f)).pack(side="right")
        bot = ctk.CTkFrame(f, fg_color="transparent"); bot.pack(fill="x", padx=8, pady=(2,8))
        ctk.CTkButton(top, text="Test", width=46, height=26, fg_color="transparent",
                      hover_color=C["accent_s"], text_color=C["muted"], font=(FONT,10),
                      command=lambda: self._test_llm("openai_compat", lambda: {
                          "base_url": url_e.get().strip(),
                          "api_key":  key_e.get().strip(),
                          "model":    model_e.get().strip()},
                          name_e.get().strip() or "Provider")).pack(side="right", padx=(0,2))
        key_e = self._entry(bot, data.get("api_key",""), 190, show="•", placeholder="API key")
        key_e.pack(side="left", padx=(0,4))
        model_e = self._entry(bot, data.get("model",""), 190, placeholder="model id")
        model_e.pack(side="left", fill="x", expand=True)
        self._custom_rows.append((name_e, url_e, key_e, model_e, f))

    def _remove_custom(self, frame):
        self._custom_rows = [r for r in self._custom_rows if r[4] is not frame]
        frame.destroy()

    def _add_mcp_row(self, data=None):
        data = data or {}
        f = ctk.CTkFrame(self._mcp_box, fg_color=C["panel"], corner_radius=10)
        f.pack(fill="x", padx=2, pady=3)
        top = ctk.CTkFrame(f, fg_color="transparent"); top.pack(fill="x", padx=8, pady=(8,2))
        name_e = self._entry(top, data.get("name",""), 120, placeholder="Name")
        name_e.pack(side="left", padx=(0,4))
        en_var = ctk.BooleanVar(value=data.get("enabled", True))
        ctk.CTkSwitch(top, variable=en_var, text="enabled", font=(FONT,10),
                      text_color=C["muted"], progress_color=C["accent"],
                      width=80).pack(side="left", padx=4)
        ctk.CTkButton(top, text="✕", width=26, height=26, fg_color="transparent",
                      hover_color=C["red"], text_color=C["muted"], font=(FONT,11),
                      command=lambda: self._remove_mcp(f)).pack(side="right")
        cmd_e = self._entry(f, data.get("command",""), 440,
                            placeholder="command to launch the MCP server")
        cmd_e.pack(fill="x", padx=8, pady=(2,8))
        # env (e.g. tokens) preserved but not shown; carried through save
        self._mcp_rows.append((name_e, cmd_e, en_var, data.get("env") or {}, f))

    def _remove_mcp(self, frame):
        self._mcp_rows = [r for r in self._mcp_rows if r[4] is not frame]
        frame.destroy()

    def _mcp_catalog(self):
        home = __import__("os").path.expanduser("~")
        desktop = next((d for d in (home + "\\Desktop", home + "\\OneDrive\\Desktop")
                        if __import__("os").path.isdir(d)), home)
        return [
            ("📁 Filesystem", {"name": "filesystem", "enabled": True,
                "command": f'npx -y @modelcontextprotocol/server-filesystem "{desktop}"'}),
            ("🧠 Memory", {"name": "memory", "enabled": True,
                "command": "npx -y @modelcontextprotocol/server-memory"}),
            ("🌐 Web (Puppeteer)", {"name": "web", "enabled": True,
                "command": "npx -y @modelcontextprotocol/server-puppeteer"}),
            ("💭 Sequential thinking", {"name": "thinking", "enabled": True,
                "command": "npx -y @modelcontextprotocol/server-sequential-thinking"}),
            ("🐙 GitHub", {"name": "github", "enabled": True,
                "command": "npx -y @modelcontextprotocol/server-github",
                "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": cfg.get("github_token") or ""}}),
        ]

    def _add_preset(self, data):
        # avoid duplicates by name
        existing = {r[0].get().strip().lower() for r in self._mcp_rows}
        if data.get("name", "").lower() in existing:
            self._status.configure(text=f"'{data['name']}' already added.",
                                   text_color=C["dim"]); return
        self._add_mcp_row(dict(data))
        self._status.configure(text=f"Added '{data['name']}' — hit Apply to connect.",
                               text_color=C["green"])

    def _email_test(self):
        cfg.set("email_address", self._em_addr.get().strip())
        cfg.set("email_app_password", self._em_pass.get().strip())
        cfg.set("email_imap_host", self._em_host.get().strip() or "imap.gmail.com")
        self._status.configure(text="Testing email login…", text_color=C["dim"])
        def do():
            from core.email_client import test_connection
            ok, msg = test_connection()
            try:
                self.after(0, lambda: self._status.configure(
                    text=f"Email: {msg}", text_color=C["green"] if ok else C["red"]))
            except Exception:
                pass
        threading.Thread(target=do, daemon=True).start()

    def _ntfy_test(self):
        self._save_ntfy()
        self._status.configure(text="Sending test push…", text_color=C["dim"])
        def do():
            from core import notify
            ok = notify.push_sync("Aria", "Test notification — phone push is working! 🎉")
            msg = ("✓ Test sent — check your phone (subscribe to the topic in the ntfy app)"
                   if ok else "Test failed — check topic/server and internet")
            try:
                self.after(0, lambda: self._status.configure(
                    text=msg, text_color=C["green"] if ok else C["red"]))
            except Exception:
                pass
        threading.Thread(target=do, daemon=True).start()

    def _save_ntfy(self):
        from core import notify
        cfg.set("ntfy_enabled", self._ntfy_v.get())
        cfg.set("ntfy_server",  self._ntfy_s.get().strip() or "https://ntfy.sh")
        cfg.set("ntfy_topic",   self._ntfy_t.get().strip())
        if not cfg.get("ntfy_topic"):
            topic = notify.ensure_topic()
            self._ntfy_t.delete(0, "end"); self._ntfy_t.insert(0, topic)

    # ── actions ─────────────────────────────────────────────────────────────
    def _apply(self):
        try:
            cfg.set("llm_backend",      self._bvar.get())
            cfg.set("groq_api_key",     self._groq_k.get().strip())
            cfg.set("groq_model",       self._groq_m.get().strip())
            cfg.set("claude_api_key",   self._cl_k.get().strip())
            cfg.set("claude_model",     self._cl_m.get().strip())

            custom = []
            for name_e, url_e, key_e, model_e, _ in self._custom_rows:
                name = name_e.get().strip()
                if not name: continue
                custom.append({"name": name, "base_url": url_e.get().strip(),
                               "api_key": key_e.get().strip(),
                               "model": model_e.get().strip()})
            cfg.set("custom_llms", custom)

            servers = []
            for name_e, cmd_e, en_var, env, _ in self._mcp_rows:
                name = name_e.get().strip()
                if not name: continue
                entry = {"name": name, "command": cmd_e.get().strip(),
                         "enabled": bool(en_var.get())}
                if env: entry["env"] = env
                servers.append(entry)
            changed_mcp = servers != (cfg.get("mcp_servers") or [])
            cfg.set("mcp_servers", servers)

            self._save_ntfy()
            cfg.set("email_address",      self._em_addr.get().strip())
            cfg.set("email_app_password", self._em_pass.get().strip())
            cfg.set("email_imap_host",    self._em_host.get().strip() or "imap.gmail.com")
            cfg.set("email_smtp_host",    self._em_smtp.get().strip() or "smtp.gmail.com")
            cfg.set("user_name",        self._user.get().strip())
            cfg.set("assistant_name",   self._asst.get().strip())
            cfg.set("ollama_model",     self._model_cb.get().strip())
            cfg.set("ollama_base_url",  self._url.get().strip())
            cfg.set("context_window",   int(self._ctx.get()))
            cfg.set("whisper_model",    self._wvar.get())
            cfg.set("tts_enabled",      self._tts_v.get())
            cfg.set("tts_rate",         int(self._rate.get()))
            cfg.set("tts_volume",       float(self._vol.get()))
            cfg.set("hotkey",           self._hkey.get().strip())
            cfg.set("wake_word_enabled",self._ww_v.get())
            cfg.set("wake_word",        self._ww.get().strip())
            cfg.set("vad_enabled",      self._vad_v.get())
            cfg.set("full_control",     self._full_v.get())
            cfg.set("confirm_destructive", self._confirm_v.get())
            cfg.set("aider_model",      self._aider_m.get().strip())
            cfg.set("code_backend",
                    "claude_code" if self._cb_var.get() == "Claude Code" else "aider")
            cfg.set("github_token",     self._gh_t.get().strip())
            cfg.set("github_username",  self._gh_u.get().strip())
            cfg.set("opacity",          float(self._opa.get()))

            self._backend_menu.configure(values=self._backend_values())
            if self.tts:
                self.tts.set_enabled(cfg.get("tts_enabled")); self.tts.reload_settings()
            if self.hotkey:
                self.hotkey.restart(cfg.get("hotkey"))
            if changed_mcp:
                self._reload_connectors()
            self._status.configure(text="✓ Saved. Providers apply instantly; restart for name changes.",
                                   text_color=C["green"])
            if self.on_apply: self.on_apply()
        except Exception as e:
            self._status.configure(text=f"Error: {e}", text_color=C["red"])
            log.error(f"Settings apply: {e}")

    def _reload_connectors(self):
        self._mcp_status.configure(text="Reconnecting connectors…")
        def do():
            from core import mcp_client
            mcp_client.load_all()
            try:
                self.after(0, lambda: self._mcp_status.configure(text=self._mcp_status_text()))
            except Exception:
                pass
        threading.Thread(target=do, daemon=True).start()

    def _reset(self):
        cfg.reset()
        self._status.configure(text="✓ Reset to defaults. Restart to apply.", text_color=C["dim"])
