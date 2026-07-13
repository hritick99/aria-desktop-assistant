"""
Floating Overlay — production UI.
Uses MarkdownBubble for all messages. Streaming-safe.
"""
import customtkinter as ctk
import tkinter as tk
import threading, queue, re, os, json, time
from datetime import datetime
from typing import Optional, Callable

import config as cfg
from core.memory import get_all_facts, delete_fact
from core.voice import VoiceRecorder
from core.logger import get_logger
from ui.markdown_renderer import MarkdownBubble   # ← properly wired
from ui.buddy_face import BuddyFace, KEY_BG
from ui.theme import C, FONT, SERIF

log = get_logger("overlay")


class _Stop(BaseException):
    """Raised inside the token callback to abort a streaming response.
    Derives from BaseException so the streaming loops' `except Exception`
    guards don't swallow it — it propagates out and unwinds the call."""
    pass


_CLEAN = re.compile(
    r'\[\s*(?:FACT|REMEMBER|REMINDER|SEARCH|CODE|CODEEDIT|DELEGATE|AIDER|EMAIL|FILE|WRITE|FIND|OS|SHELL|RAG|MCP)[:\s][^\]]*\]'
    r'|\[\s*(?:CLIPBOARD|SCREENSHOT|DONE)\s*\]', re.I)


class ToolCard(ctk.CTkFrame):
    """Claude-style tool activity: collapsed one-liner, click to drill down."""
    def __init__(self, parent, **kw):
        super().__init__(parent, fg_color=C["panel"], corner_radius=12, **kw)
        self._entries = []          # [label, result | None]
        self._open = True           # start expanded so work is visible live
        hdr = ctk.CTkFrame(self, fg_color="transparent", cursor="hand2")
        hdr.pack(fill="x")
        self._chev = ctk.CTkLabel(hdr, text="▾", width=16, font=(FONT,11),
                                  text_color=C["muted"])
        self._chev.pack(side="left", padx=(10,0), pady=5)
        self._title = ctk.CTkLabel(hdr, text="Working…", font=(FONT,11),
                                   text_color=C["dim"], anchor="w")
        self._title.pack(side="left", padx=6, pady=5, fill="x", expand=True)
        self._body = ctk.CTkFrame(self, fg_color="transparent")
        self._body.pack(fill="x", padx=12, pady=(0,8))
        for w in (hdr, self._chev, self._title):
            w.bind("<Button-1>", self._toggle)

    def add_tool(self, label):
        self._entries.append([str(label), None])
        self._title.configure(text=str(label))
        if self._open: self._rebuild()

    def set_result(self, result):
        for e in reversed(self._entries):
            if e[1] is None:
                e[1] = result or ""
                break
        if self._open: self._rebuild()

    def finish(self):
        # Collapse to a tidy summary once done (still re-expandable).
        n = len(self._entries)
        self._title.configure(text=f"Used {n} tool{'s' if n != 1 else ''}",
                              text_color=C["muted"])
        if self._open:
            self._open = False
            self._chev.configure(text="▸")
            self._body.pack_forget()

    def _toggle(self, e=None):
        self._open = not self._open
        self._chev.configure(text="▾" if self._open else "▸")
        if self._open:
            self._rebuild()
            self._body.pack(fill="x", padx=12, pady=(0,8))
        else:
            self._body.pack_forget()

    def _rebuild(self):
        for w in self._body.winfo_children(): w.destroy()
        wrap = cfg.get("window_width") - 120
        for label, result in self._entries:
            ctk.CTkLabel(self._body, text=label, font=(FONT,10,"bold"),
                         text_color=C["dim"], anchor="w", justify="left",
                         wraplength=wrap).pack(fill="x", pady=(4,0))
            if result is None:
                ctk.CTkLabel(self._body, text="⏳ working…", font=("Consolas",9),
                             text_color=C["reminder"], anchor="w").pack(fill="x", pady=(0,2))
            else:
                prev = result.strip()
                if len(prev) > 400: prev = prev[:400] + " …"
                ctk.CTkLabel(self._body, text=prev, font=("Consolas",9),
                             text_color=C["muted"], anchor="w", justify="left",
                             wraplength=wrap).pack(fill="x", pady=(0,2))


class ReminderBanner(ctk.CTkFrame):
    def __init__(self, parent, title, on_dismiss, on_done=None, on_snooze=None, **kw):
        super().__init__(parent, fg_color=C["panel"], border_width=1,
                         border_color=C["reminder"], corner_radius=8, **kw)
        inner = ctk.CTkFrame(self, fg_color="transparent"); inner.pack(fill="x", padx=8, pady=6)
        ctk.CTkLabel(inner, text="🔔", font=(FONT,16), text_color=C["reminder"]).pack(side="left", padx=(4,8))
        ctk.CTkLabel(inner, text=title, font=(FONT,12,"bold"), text_color=C["text"],
                     anchor="w").pack(side="left", fill="x", expand=True)
        ctk.CTkButton(inner, text="✕", width=24, height=24, fg_color="transparent",
                      hover_color=C["red"], text_color=C["dim"], font=(FONT,11),
                      command=on_dismiss).pack(side="right")
        if on_snooze:
            ctk.CTkButton(inner, text="+10 min", width=58, height=24,
                          fg_color="transparent", hover_color=C["panel2"],
                          text_color=C["dim"], font=(FONT,10),
                          command=on_snooze).pack(side="right", padx=2)
        if on_done:
            ctk.CTkButton(inner, text="✓ Done", width=58, height=24,
                          fg_color="transparent", hover_color=C["panel2"],
                          text_color=C["green"], font=(FONT,10,"bold"),
                          command=on_done).pack(side="right", padx=2)


class MemoryPanel(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title(f"{cfg.get('assistant_name')} — Memory")
        self.geometry("420x520"); self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True); self._build()

    def _build(self):
        ctk.CTkLabel(self, text="🧠  What I Remember", font=(FONT,14,"bold"),
                     text_color=C["text"]).pack(pady=(16,4))
        try:
            from core.knowledge_graph import stats
            ne, nr = stats()
        except Exception:
            ne, nr = 0, 0
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(pady=(0,8))
        ctk.CTkLabel(bar, text=f"{ne} entities · {nr} relations", font=(FONT,10),
                     text_color=C["dim"]).pack(side="left", padx=8)
        ctk.CTkButton(bar, text="🕸 View graph", width=110, height=26,
                      fg_color=C["accent"], hover_color=C["accent2"],
                      text_color=C["bg"], font=(FONT,11), corner_radius=13,
                      command=self._open_graph).pack(side="left", padx=4)
        self._scroll = ctk.CTkScrollableFrame(self, fg_color=C["panel"], corner_radius=10)
        self._scroll.pack(fill="both", expand=True, padx=14, pady=(0,14))
        self._refresh()

    def _open_graph(self):
        from ui.graph_panel import GraphPanel
        GraphPanel(self.master)

    def _refresh(self):
        for w in self._scroll.winfo_children(): w.destroy()
        facts = get_all_facts()
        if not facts:
            ctk.CTkLabel(self._scroll, text="No facts yet — chat a bit!",
                         text_color=C["muted"], font=(FONT,12)).pack(pady=40); return
        for row in facts:
            f = ctk.CTkFrame(self._scroll, fg_color=C["input_bg"], corner_radius=8)
            f.pack(fill="x", padx=4, pady=3, ipady=2)
            ctk.CTkLabel(f, text=f"• {row['fact']}", font=(FONT,11), text_color=C["text"],
                         anchor="w", wraplength=320).pack(side="left", padx=10, pady=4, fill="x", expand=True)
            fid = row["id"]
            ctk.CTkButton(f, text="✕", width=28, height=24, fg_color="transparent",
                          hover_color=C["red"], text_color=C["dim"], font=(FONT,11),
                          command=lambda i=fid: (delete_fact(i), self._refresh())).pack(side="right", padx=6)


class HistoryPanel(ctk.CTkToplevel):
    """Browse past chat sessions; open one back into the chat to continue it."""
    def __init__(self, parent, on_open):
        super().__init__(parent)
        self.on_open = on_open
        self.title(f"{cfg.get('assistant_name')} — History")
        self.geometry("440x560"); self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True); self._build()

    def _build(self):
        ctk.CTkLabel(self, text="🕘  Past Conversations", font=(SERIF,15,"bold"),
                     text_color=C["text"]).pack(pady=(16,2))
        ctk.CTkLabel(self, text="Click a session to reopen and continue it",
                     font=(FONT,10), text_color=C["dim"]).pack(pady=(0,10))
        self._scroll = ctk.CTkScrollableFrame(self, fg_color=C["panel"], corner_radius=10)
        self._scroll.pack(fill="both", expand=True, padx=14, pady=(0,14))
        self._refresh()

    def _fmt(self, ts):
        try:
            import calendar
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            local = datetime.fromtimestamp(calendar.timegm(dt.timetuple()))
            return local.strftime("%d %b, %H:%M")
        except Exception:
            return ts or ""

    def _refresh(self):
        for w in self._scroll.winfo_children(): w.destroy()
        from core.memory import list_sessions
        sessions = list_sessions()
        current = getattr(self.master.assistant, "session_id", None)
        sessions = [s for s in sessions if s["session_id"] != current]
        if not sessions:
            ctk.CTkLabel(self._scroll, text="No past sessions yet.",
                         text_color=C["muted"], font=(FONT,12)).pack(pady=40); return
        for s in sessions:
            sid = s["session_id"]
            row = ctk.CTkFrame(self._scroll, fg_color=C["input_bg"], corner_radius=8,
                               cursor="hand2")
            row.pack(fill="x", padx=4, pady=3)
            l1 = ctk.CTkLabel(row, text=s["preview"], font=(FONT,12), text_color=C["text"],
                              anchor="w", justify="left", cursor="hand2")
            l1.pack(anchor="w", padx=10, pady=(6,0))
            l2 = ctk.CTkLabel(row, text=f"{self._fmt(s['ended'])}  ·  {s['msgs']} messages",
                              font=(FONT,9), text_color=C["muted"], anchor="w", cursor="hand2")
            l2.pack(anchor="w", padx=10, pady=(0,6))
            # Make the entire row clickable (labels included).
            for w in (row, l1, l2):
                w.bind("<Button-1>", lambda e, i=sid: self._open(i))

    def _open(self, session_id):
        self.on_open(session_id)
        self.destroy()


class OverlayApp(ctk.CTk):
    def __init__(self, assistant, tts_engine=None, hotkey_listener=None):
        super().__init__()
        self.assistant       = assistant
        self.tts             = tts_engine
        self.hotkey_listener = hotkey_listener
        self._collapsed      = False
        self._is_thinking    = False
        self._is_recording   = False
        self._visible        = True
        self._tok_q:   queue.Queue = queue.Queue()
        self._rem_q:   queue.Queue = queue.Queue()
        self._stop_evt = threading.Event()
        self._cur_bubble: Optional[MarkdownBubble] = None
        self._cur_text    = ""
        self._mem_panel   = None
        self._hist_panel  = None
        self._code_panel  = None
        self._set_panel   = None
        self._orb_btn_face = None
        self._last_interaction = time.time()

        ctk.set_appearance_mode("dark")
        self._configure_window()
        self._build_ui()
        self._bind_drag(self.title_bar)
        self._poll_tokens()
        self._poll_reminders()
        self._poll_face()

        self.voice = VoiceRecorder(on_status=self._on_voice_status)
        self.after(500, self._show_welcome)

    def _configure_window(self):
        self.title(cfg.get("assistant_name"))
        w,h = cfg.get("window_width"), cfg.get("window_height")
        x,y = self._clamp(cfg.get("window_x"), cfg.get("window_y"), w, h)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.configure(fg_color=KEY_BG)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", cfg.get("opacity"))
        self.resizable(True, True)
        # Transparent window margins → the UI reads as a floating rounded card.
        try: self.attributes("-transparentcolor", KEY_BG)
        except tk.TclError: pass

    def _build_ui(self):
        # Rounded floating card — everything lives inside this
        self.card = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=18,
                                 border_width=1, border_color=C["border"])
        self.card.pack(fill="both", expand=True, padx=7, pady=7)

        # Title bar
        self.title_bar = ctk.CTkFrame(self.card, height=58, fg_color="transparent", corner_radius=0)
        self.title_bar.pack(fill="x", padx=6, pady=(6,0)); self.title_bar.pack_propagate(False)
        self.orb = BuddyFace(self.title_bar, size=44,
                             get_color=self._buddy_color, bg=C["bg"])
        self.orb.pack(side="left", padx=(6,8), pady=6)
        self.orb.start()
        name_box = ctk.CTkFrame(self.title_bar, fg_color="transparent")
        name_box.pack(side="left", pady=8)
        ctk.CTkLabel(name_box, text=cfg.get("assistant_name"), font=(SERIF,17,"bold"),
                     text_color=C["text"], anchor="w").pack(anchor="w")
        self.subtitle_lbl = ctk.CTkLabel(name_box, text="online", font=(FONT,10),
                                         text_color=C["muted"], anchor="w")
        self.subtitle_lbl.pack(anchor="w")
        ctrl = ctk.CTkFrame(self.title_bar, fg_color="transparent"); ctrl.pack(side="right", padx=4)
        for txt, cmd, hov in [("✚",self._new_session,C["accent_s"]),("🕘",self._open_history,C["panel2"]),
                               ("✦",self._open_memory,C["panel2"]),("⚙",self._open_settings,C["panel2"]),
                               ("↓",self._export,C["panel2"]),("—",self._collapse,C["panel2"]),("✕",self.hide,C["red"])]:
            ctk.CTkButton(ctrl, text=txt, width=30, height=30, fg_color="transparent",
                          hover_color=hov, font=(FONT,12), text_color=C["muted"],
                          corner_radius=15, command=cmd).pack(side="left", padx=1)

        # Tool strip — quiet text actions
        self.tool_bar = ctk.CTkFrame(self.card, height=34, fg_color="transparent", corner_radius=0)
        self.tool_bar.pack(fill="x", padx=12, pady=(0,2)); self.tool_bar.pack_propagate(False)
        for i, (lbl, cmd) in enumerate([
                ("Screen",self._tool_screen),("Search",self._tool_search),
                ("Code",self._tool_code),("Clip",self._tool_clip),
                ("Remind",self._tool_remind),("Docs",self._tool_rag)]):
            self.tool_bar.grid_columnconfigure(i, weight=1, uniform="chips")
            ctk.CTkButton(self.tool_bar, text=lbl, width=10, height=26,
                          fg_color="transparent", hover_color=C["panel2"],
                          font=(FONT,10), text_color=C["muted"],
                          corner_radius=13, command=cmd).grid(row=0, column=i,
                                                              sticky="ew", padx=1, pady=4)

        # Banner slot
        self.banner_slot = ctk.CTkFrame(self.card, fg_color="transparent", height=0)
        self.banner_slot.pack(fill="x", padx=10)

        # Chat
        self.chat_frame = ctk.CTkScrollableFrame(self.card, fg_color="transparent", corner_radius=0)
        self.chat_frame.pack(fill="both", expand=True, padx=10, pady=(2,0))

        # Status bar
        self.status_bar = ctk.CTkFrame(self.card, height=24, fg_color="transparent", corner_radius=0)
        self.status_bar.pack(fill="x", side="bottom", padx=12); self.status_bar.pack_propagate(False)
        self.status_lbl = ctk.CTkLabel(self.status_bar, text="", font=(FONT,10),
                                        text_color=C["muted"]); self.status_lbl.pack(side="left")
        self._tts_var = ctk.BooleanVar(value=cfg.get("tts_enabled"))
        ctk.CTkSwitch(self.status_bar, variable=self._tts_var, text="🔊", width=44, height=18,
                      progress_color=C["accent"], font=(FONT,10), text_color=C["muted"],
                      command=self._toggle_tts).pack(side="right")

        # Input bar — a clean rounded pill: [＋]  text …  [🎙] [send]
        self.input_bar = ctk.CTkFrame(self.card, height=52, fg_color=C["input"],
                                      corner_radius=26, border_width=1, border_color=C["border"])
        self.input_bar.pack(fill="x", side="bottom", padx=12, pady=(2,12))
        self.input_bar.pack_propagate(False)

        # left: attach (+)
        self.attach_btn = ctk.CTkButton(self.input_bar, text="＋", width=30, height=30,
                                        fg_color="transparent", hover_color=C["panel2"],
                                        font=(FONT,18), text_color=C["muted"],
                                        corner_radius=15, command=self._attach_image)
        self.attach_btn.pack(side="left", padx=(9,2), pady=11)

        # right: send button (becomes a stop button while thinking)
        self.send_btn = ctk.CTkButton(self.input_bar, text="↑", width=36, height=36,
                                       fg_color=C["accent"], hover_color=C["accent2"],
                                       font=(FONT,17,"bold"), text_color=C["bg"],
                                       corner_radius=18, command=self._on_send)
        self.send_btn.pack(side="right", padx=(2,8), pady=8)
        # mic sits just left of send
        self.mic_btn = ctk.CTkButton(self.input_bar, text="🎙", width=30, height=30,
                                      fg_color="transparent", hover_color=C["panel2"],
                                      font=(FONT,15), text_color=C["muted"], corner_radius=15)
        self.mic_btn.pack(side="right", padx=(0,2), pady=11)
        self.mic_btn.bind("<ButtonPress-1>",   self._mic_press)
        self.mic_btn.bind("<ButtonRelease-1>", self._mic_release)

        # entry fills the middle
        self.input_field = ctk.CTkEntry(self.input_bar,
                                         placeholder_text=f"Message {cfg.get('assistant_name')}…",
                                         font=(FONT,13), fg_color="transparent", border_width=0,
                                         text_color=C["text"],
                                         placeholder_text_color=C["muted"], height=34)
        self.input_field.pack(side="left", fill="x", expand=True, padx=(6,4), pady=9)
        self.input_field.bind("<Return>", self._on_send)
        self.input_field.bind("<Control-v>", self._paste_maybe_image, add="+")
        self._bind_edit_menu(self.input_field)

        # Drag-to-resize grip in the bottom-right corner
        self.resize_grip = ctk.CTkLabel(self.card, text="⤡", font=(FONT,13),
                                        text_color=C["muted"], cursor="size_nw_se")
        self.resize_grip.place(relx=1.0, rely=1.0, anchor="se", x=-3, y=-1)
        self.resize_grip.bind("<ButtonPress-1>", self._rs_start)
        self.resize_grip.bind("<B1-Motion>",     self._rs_drag)

    def _bind_edit_menu(self, ctk_entry):
        """Right-click Cut/Copy/Paste on an entry (Tk has no native menu)."""
        inner = getattr(ctk_entry, "_entry", ctk_entry)
        def show(e):
            m = tk.Menu(self, tearoff=0, bg=C["panel"], fg=C["text"], bd=0,
                        activebackground=C["accent"], activeforeground=C["bg"])
            for label, ev in (("Cut","<<Cut>>"), ("Copy","<<Copy>>"), ("Paste","<<Paste>>")):
                m.add_command(label=label, command=lambda ev=ev: inner.event_generate(ev))
            m.add_separator()
            m.add_command(label="Select all",
                          command=lambda: inner.select_range(0, "end"))
            m.tk_popup(e.x_root, e.y_root)
            return "break"
        inner.bind("<Button-3>", show)

    def _bind_drag(self, widget):
        widget.bind("<ButtonPress-1>",  self._ds)
        widget.bind("<B1-Motion>",      self._dm)
        for child in widget.winfo_children():
            child.bind("<ButtonPress-1>", self._ds)
            child.bind("<B1-Motion>",     self._dm)

    def _rs_start(self, e):
        self._rw = self.winfo_width(); self._rh = self.winfo_height()
        self._rx = e.x_root; self._ry = e.y_root

    def _rs_drag(self, e):
        w = max(340, self._rw + (e.x_root - self._rx))
        h = max(380, self._rh + (e.y_root - self._ry))
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(w, sw - self.winfo_x())
        h = min(h, sh - self.winfo_y() - 40)
        self.geometry(f"{int(w)}x{int(h)}")
        cfg.set("window_width", int(w)); cfg.set("window_height", int(h))

    def _clamp(self, x, y, w, h):
        """Keep a w×h window fully inside the primary screen."""
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = max(0, min(int(x), sw - int(w)))
        y = max(0, min(int(y), sh - int(h) - 40))   # leave room for the taskbar
        return x, y

    def _ds(self, e): self._dx = e.x_root - self.winfo_x(); self._dy = e.y_root - self.winfo_y()
    def _dm(self, e):
        x, y = self._clamp(e.x_root-self._dx, e.y_root-self._dy,
                           self.winfo_width(), self.winfo_height())
        self.geometry(f"+{x}+{y}"); cfg.set("window_x",x); cfg.set("window_y",y)

    def _collapse(self):
        self._collapsed = True
        sz = cfg.get("collapsed_size")
        self.card.pack_forget()
        # Reuse a single orb face across collapse/expand (creating/destroying
        # an animated canvas each time is what made the transition stutter).
        if self._orb_btn_face is None:
            self._orb_btn_face = BuddyFace(self, size=sz, get_color=self._buddy_color, bg=KEY_BG)
            self._orb_btn_face.bind("<ButtonPress-1>",   self._orb_press)
            self._orb_btn_face.bind("<B1-Motion>",       self._orb_motion)
            self._orb_btn_face.bind("<ButtonRelease-1>", self._orb_release)
        self.geometry(f"{sz}x{sz}")
        self._orb_btn_face.pack()
        self._orb_btn_face.start()
        self.update_idletasks()

    def _orb_press(self, e):
        self._dx = e.x_root - self.winfo_x(); self._dy = e.y_root - self.winfo_y()
        self._orb_px = e.x_root; self._orb_py = e.y_root; self._orb_moved = False

    def _orb_motion(self, e):
        if abs(e.x_root - self._orb_px) + abs(e.y_root - self._orb_py) > 4:
            self._orb_moved = True
        sz = cfg.get("collapsed_size")
        x, y = self._clamp(e.x_root - self._dx, e.y_root - self._dy, sz, sz)
        self.geometry(f"+{x}+{y}"); cfg.set("window_x", x); cfg.set("window_y", y)

    def _orb_release(self, e):
        if not self._orb_moved:
            self._expand()

    def _expand(self):
        self._collapsed = False
        if self._orb_btn_face is not None:
            self._orb_btn_face.stop()
            self._orb_btn_face.pack_forget()   # hide, don't destroy — reused next collapse
        w, h = cfg.get("window_width"), cfg.get("window_height")
        # Expand from wherever the float icon sits, but keep the whole card on-screen.
        x, y = self._clamp(self.winfo_x(), self.winfo_y(), w, h)
        # Grow the window and lay out the card in one settled repaint (no pop-in).
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.update_idletasks()
        self.card.pack(fill="both", expand=True, padx=7, pady=7)
        self.update_idletasks()
        cfg.set("window_x", x); cfg.set("window_y", y)

    def toggle(self): self.after(0, self._do_toggle)
    def _do_toggle(self): self.hide() if self._visible else self.show()
    def show(self): self._visible=True; self.deiconify(); self.lift(); self.attributes("-topmost",True)
    def hide(self): self._visible=False; self.withdraw()

    def _open_memory(self):
        if self._mem_panel and self._mem_panel.winfo_exists(): self._mem_panel.lift()
        else: self._mem_panel = MemoryPanel(self)

    def _new_session(self):
        """Start a fresh conversation (the old one stays saved in history)."""
        if self._is_thinking:
            return
        import uuid
        from core.memory import get_or_create_session
        self.assistant.session_id = str(uuid.uuid4())
        get_or_create_session(self.assistant.session_id)
        for w in self.chat_frame.winfo_children():
            w.destroy()
        self._cur_bubble = None; self._cur_text = ""
        self._show_welcome()
        self._set_status("✚ New conversation", clear_after=3000)

    def _open_history(self):
        if self._hist_panel and self._hist_panel.winfo_exists():
            self._hist_panel.lift(); return
        self._hist_panel = HistoryPanel(self, on_open=self._load_session)

    def _open_code(self):
        if getattr(self, "_code_panel", None) and self._code_panel.winfo_exists():
            self._code_panel.lift(); return
        from ui.code_panel import CodePanel
        self._code_panel = CodePanel(self)

    def _load_session(self, session_id):
        """Reopen a past session into the chat and continue it.
        Renders in small batches so the UI never freezes on long chats."""
        from core.memory import get_session_messages, get_or_create_session
        msgs = get_session_messages(session_id)
        for w in self.chat_frame.winfo_children():
            w.destroy()
        self.assistant.session_id = session_id
        get_or_create_session(session_id)

        # Keep only messages with visible content; show the most recent 40.
        cleaned = [(m["role"], _CLEAN.sub("", m["content"]).strip()) for m in msgs]
        cleaned = [(r, c) for r, c in cleaned if c]
        LIMIT = 40
        if len(cleaned) > LIMIT:
            hidden = len(cleaned) - LIMIT
            cleaned = cleaned[-LIMIT:]
            self._add_bubble("assistant", f"… {hidden} earlier messages hidden …",
                             scroll=False)
        self._set_status("↩ Loading conversation…")

        def render(i=0):
            batch = cleaned[i:i+8]
            for role, content in batch:
                self._add_bubble(role, content, scroll=False, lite=True)
            if i + 8 < len(cleaned):
                self.after(1, lambda: render(i + 8))
            else:
                self._scroll_bottom()
                self._set_status("↩ Continuing past session", clear_after=4000)
        render()

    def _open_settings(self):
        if self._set_panel and self._set_panel.winfo_exists(): self._set_panel.lift(); return
        from ui.settings import SettingsPanel
        self._set_panel = SettingsPanel(self, on_apply=self._on_settings_applied,
                                         tts_engine=self.tts, hotkey_listener=self.hotkey_listener)

    def _on_settings_applied(self):
        self.attributes("-alpha", cfg.get("opacity")); self._tts_var.set(cfg.get("tts_enabled"))

    def _export(self):
        try:
            from core.memory import get_session_messages
            msgs = get_session_messages(self.assistant.session_id)
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Desktop may be redirected (OneDrive) — pick the first that exists
            home = os.path.expanduser("~")
            desktop = next((d for d in (os.path.join(home, "Desktop"),
                                        os.path.join(home, "OneDrive", "Desktop"))
                            if os.path.isdir(d)), home)
            path = os.path.join(desktop, f"aria_chat_{ts}.json")
            with open(path,"w",encoding="utf-8") as f: json.dump(msgs, f, ensure_ascii=False, indent=2)
            self._set_status(f"✓ Exported: aria_chat_{ts}.json")
        except Exception as e: self._set_status(f"Export failed: {e}")

    # ── Tool buttons ────────────────────────────────────────────────────────────
    def _tool_screen(self):  self._send_as_user("Look at my screen and describe what you see.")
    def _tool_clip(self):    self._send_as_user("Read my clipboard and tell me what's in it.")
    def _tool_rag(self):     self._prefill("Search my documents for: ")
    def _tool_search(self):  self._prefill("Search for: ")
    def _tool_code(self):    self._open_code()
    def _tool_remind(self):  self._prefill("Remind me to ")

    def _prefill(self, text):
        self.input_field.delete(0,"end"); self.input_field.insert(0,text)
        self.input_field.focus(); self.input_field.icursor("end")

    def _send_as_user(self, text):
        if self._is_thinking: return
        self._add_bubble("user", text, datetime.now().strftime("%H:%M"))
        self._start_response(text)

    # ── Image input ───────────────────────────────────────────────────────────
    def _attach_image(self):
        if self._is_thinking: return
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Send an image to Aria",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                       ("All files", "*.*")])
        self.lift()
        if path:
            self._send_image_file(path)

    def _paste_maybe_image(self, e=None):
        """Ctrl+V: if the clipboard holds an image, send it; else normal paste."""
        try:
            from PIL import ImageGrab
            img = ImageGrab.grabclipboard()
        except Exception:
            img = None
        if img is not None and hasattr(img, "save"):
            import io, base64
            buf = io.BytesIO(); img.convert("RGB").save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            text = self.input_field.get().strip()
            self.input_field.delete(0, "end")
            self._send_image(b64, text)
            return "break"       # consume so it doesn't also paste text
        return None              # let normal text paste happen

    def _send_image_file(self, path):
        try:
            import base64, io
            from PIL import Image
            img = Image.open(path)
            if img.width > 1280:
                r = 1280 / img.width
                img = img.resize((1280, int(img.height * r)))
            buf = io.BytesIO(); img.convert("RGB").save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            self._send_image(b64, self.input_field.get().strip())
            self.input_field.delete(0, "end")
        except Exception as ex:
            log.error(f"Attach image: {ex}")
            self._set_status(f"Couldn't load image: {ex}", clear_after=4000)

    def _send_image(self, b64, text=""):
        if self._is_thinking: return
        prompt = text or "Describe this image in detail."
        self._add_bubble("user", text or "🖼 (image)", datetime.now().strftime("%H:%M"))
        self._add_image_bubble(b64)
        self._start_response(prompt, image_b64=b64)

    # ── Voice ────────────────────────────────────────────────────────────────────
    def _on_voice_status(self, msg): self.after(0, lambda: self._set_status(msg))

    def _mic_press(self, e=None):
        if self._is_thinking or self._is_recording: return
        self._is_recording = True
        self._last_interaction = time.time()
        self.mic_btn.configure(fg_color=C["mic_on"], text_color="#FFFFFF")
        self._face("listening")
        threading.Thread(target=self.voice.start_recording, daemon=True).start()

    def _mic_release(self, e=None):
        if not self._is_recording: return
        self._is_recording = False
        self.mic_btn.configure(fg_color="transparent", text_color=C["muted"])
        self._face("idle")
        def go():
            text = self.voice.stop_and_transcribe()
            if text: self.after(0, lambda: self._inject_voice(text))
        threading.Thread(target=go, daemon=True).start()

    def _inject_voice(self, text):
        self.input_field.delete(0,"end"); self.input_field.insert(0,text); self._on_send()

    def _toggle_tts(self):
        v = self._tts_var.get(); cfg.set("tts_enabled", v)
        if self.tts: self.tts.set_enabled(v)

    # ── Reminders ─────────────────────────────────────────────────────────────────
    def notify_reminder(self, title):
        self._rem_q.put(title)

    def _poll_reminders(self):
        while True:
            try: title = self._rem_q.get_nowait()
            except queue.Empty: break
            self._show_banner(title)
            self._add_bubble("assistant", f"🔔 Reminder: {title}", datetime.now().strftime("%H:%M"))
            if self.tts and cfg.get("tts_enabled"): self.tts.speak(f"Reminder: {title}")
            if not self._visible: self.show()
        self.after(1000, self._poll_reminders)

    def _show_banner(self, title):
        for w in self.banner_slot.winfo_children(): w.destroy()
        def dismiss():
            for w in self.banner_slot.winfo_children(): w.destroy()
        def done():
            try:
                from core.reminders import mark_done_by_title
                mark_done_by_title(title)
                self._set_status("✓ Marked done", clear_after=4000)
            except Exception as e:
                log.error(f"Mark done: {e}")
            dismiss()
        def snooze():
            try:
                eng = self.assistant._reminder_engine
                if eng:
                    eng.snooze(title, 10)
                    self._set_status("⏰ Snoozed — again in 10 min", clear_after=4000)
            except Exception as e:
                log.error(f"Snooze: {e}")
            dismiss()
        b = ReminderBanner(self.banner_slot, title, on_dismiss=dismiss,
                           on_done=done, on_snooze=snooze)
        b.pack(fill="x", padx=6, pady=3)
        self.after(25000, dismiss)

    # ── Chat ──────────────────────────────────────────────────────────────────────
    def _show_welcome(self):
        h = datetime.now().hour
        g = "Good morning" if h<12 else "Good afternoon" if h<17 else "Good evening"
        n = cfg.get("user_name"); a = cfg.get("assistant_name")
        msg = (f"{g}, {n}! I'm {a} — your autonomous AI assistant.\n"
               f"I remember our conversations, can search the web, run code, read files, "
               f"control your OS, and set reminders. How can I help?")
        self._add_bubble("assistant", msg, datetime.now().strftime("%H:%M"))
        if self.tts and cfg.get("tts_enabled"): self.tts.speak(f"{g}, {n}! How can I help?")

    def _on_send(self, e=None):
        if self._is_thinking: return
        text = self.input_field.get().strip()
        if not text: return
        self.input_field.delete(0,"end")
        self._last_interaction = time.time()
        self._add_bubble("user", text, datetime.now().strftime("%H:%M"))
        self._start_response(text)

    def _add_bubble(self, role, content, ts="", scroll=True, lite=False) -> MarkdownBubble:
        wrap = max(260, self.winfo_width() - 90)
        b = MarkdownBubble(self.chat_frame, role, content, ts, wrap_width=wrap, lite=lite)
        b.pack(fill="x", padx=2, pady=4)
        if scroll: self._scroll_bottom()
        return b

    def _add_image_bubble(self, b64: str):
        """Render a captured screenshot inline in the chat, above the reply."""
        try:
            import base64, io
            from PIL import Image
            raw = base64.b64decode(b64)
            img = Image.open(io.BytesIO(raw))
            maxw = cfg.get("window_width") - 60
            if img.width > maxw:
                r = maxw / img.width
                img = img.resize((int(maxw), int(img.height * r)))
            ck = ctk.CTkImage(light_image=img, dark_image=img,
                              size=(img.width, img.height))
            frame = ctk.CTkFrame(self.chat_frame, fg_color="transparent")
            lbl = ctk.CTkLabel(frame, image=ck, text="")
            lbl.image = ck            # keep a ref so it isn't garbage-collected
            lbl.pack(anchor="w", padx=6, pady=2)
            # Click to open full-size in the default image viewer
            path = os.path.join(
                os.environ.get("TEMP", os.path.expanduser("~")),
                f"aria_screenshot_{datetime.now():%H%M%S}.png")
            with open(path, "wb") as f:
                f.write(raw)
            lbl.bind("<Button-1>", lambda e, p=path: os.startfile(p))
            lbl.configure(cursor="hand2")
            if getattr(self, "_cur_bubble", None):
                frame.pack(fill="x", padx=4, pady=2, before=self._cur_bubble)
            else:
                frame.pack(fill="x", padx=4, pady=2)
            self._scroll_bottom()
        except Exception as e:
            log.error(f"Image bubble: {e}")

    def _scroll_bottom(self):
        self.after(60, lambda: self.chat_frame._parent_canvas.yview_moveto(1.0))

    def _set_status(self, msg, clear_after=0):
        self.status_lbl.configure(text=msg)
        if clear_after: self.after(clear_after, lambda: self.status_lbl.configure(text=""))

    def _buddy_color(self) -> str:
        """Eye colour: state overrides for record/think, else emotional mood."""
        if self._is_recording: return C["orb_rec"]
        if self._is_thinking:  return C["orb_think"]
        try:
            from core.emotional_state import get_orb_color
            return get_orb_color()
        except Exception:
            return C["orb_idle"]

    def _face(self, state: str):
        for f in (getattr(self, "orb", None), getattr(self, "_orb_btn_face", None)):
            if f is not None:
                try: f.set_state(state)
                except Exception: pass

    def _set_thinking(self, v):
        self._is_thinking = v
        self._face("thinking" if v else "idle")
        # Send button becomes a Stop button while a response is in progress.
        if v:
            self.send_btn.configure(text="■", fg_color=C["red"], hover_color=C["red"],
                                    state="normal", command=self._stop)
        else:
            self.send_btn.configure(text="↑", fg_color=C["accent"],
                                    hover_color=C["accent2"], state="normal",
                                    command=self._on_send)
        if not v: self.after(3000, lambda: self.status_lbl.configure(text=""))

    def _stop(self):
        """Interrupt the in-progress response immediately."""
        self._stop_evt.set()
        if getattr(self, "_cur_card", None):
            self._cur_card.finish()
        if self._cur_bubble:
            shown = getattr(self, "_final_reply", None)
            if shown is None:
                shown = _CLEAN.sub("", self._cur_text).strip()
            self._cur_bubble.update_text((shown + "  ⏹") if shown else "⏹ Stopped")
        # Detach so any late tokens from the worker become no-ops.
        self._cur_bubble = None; self._cur_text = ""; self._cur_card = None
        self._set_thinking(False)
        self._set_status("⏹ Stopped", clear_after=3000)

    def _start_response(self, user_text, image_b64=None):
        self._stop_evt.clear()
        self._set_thinking(True)
        self._cur_bubble = self._add_bubble("assistant", "▌", datetime.now().strftime("%H:%M"))
        self._cur_text   = ""
        self._cur_card   = None
        self._final_reply = None

        # Token callback that also honours a stop request. Raising _Stop
        # (a BaseException) unwinds the streaming loop cleanly.
        def on_token(tok):
            if self._stop_evt.is_set(): raise _Stop()
            self._tok_q.put(tok)
        # Structured events share the token queue so ordering is preserved.
        def on_tool_start(name):   self._tok_q.put(("tool", name))
        def on_tool_done(result):  self._tok_q.put(("tool_done", result))
        def on_image(b64):         self._tok_q.put(("image", b64))

        def run():
            try:
                reply = self.assistant.chat(user_text, on_token=on_token,
                                             on_tool_start=on_tool_start, on_tool_done=on_tool_done,
                                             on_image=on_image, image_b64=image_b64)
                if not self._stop_evt.is_set():
                    self._tok_q.put(("final", reply))
                    if self.tts and cfg.get("tts_enabled"): self.tts.speak(reply)
            except _Stop:
                pass  # user interrupted — already handled in _stop()
            except Exception as ex:
                self._tok_q.put(f"\n\n⚠️ Error: {ex}"); log.error(f"Chat: {ex}")
            finally: self._tok_q.put(None)

        threading.Thread(target=run, daemon=True).start()

    def _poll_tokens(self):
        updated = False
        while True:
            try: tok = self._tok_q.get_nowait()
            except queue.Empty: break
            # After a stop, drain and ignore everything until the sentinel.
            if self._stop_evt.is_set() and tok is not None:
                continue
            if tok is None:
                self._set_thinking(False)
                if getattr(self, "_cur_card", None):
                    self._cur_card.finish()
                if self._cur_bubble:
                    final = getattr(self, "_final_reply", None)
                    if final is None:
                        final = _CLEAN.sub("", self._cur_text).strip()
                    self._cur_bubble.update_text(final or "(no response)")
                self._cur_bubble = None; self._cur_text = ""
                self._cur_card = None; self._final_reply = None
                break
            if isinstance(tok, tuple):
                kind, payload = tok
                if kind == "tool":
                    # Tool fired: the streamed text so far was tag chatter — hide it
                    if self._cur_card is None and self._cur_bubble:
                        self._cur_card = ToolCard(self.chat_frame)
                        self._cur_card.pack(fill="x", padx=10, pady=2,
                                            before=self._cur_bubble)
                    if self._cur_card: self._cur_card.add_tool(payload)
                    self._cur_text = ""
                    if self._cur_bubble: self._cur_bubble.update_text("▌")
                    self._set_status(str(payload))
                elif kind == "tool_done":
                    if getattr(self, "_cur_card", None):
                        self._cur_card.set_result(payload)
                    self._set_status("✓ " + str(payload or "")[:80].replace("\n", " "))
                elif kind == "image":
                    self._add_image_bubble(payload)
                elif kind == "final":
                    self._final_reply = _CLEAN.sub("", payload or "").strip()
                updated = True
                continue
            self._cur_text += tok
            if self._is_thinking: self._face("speaking")
            if self._cur_bubble:
                display = _CLEAN.sub("", self._cur_text) + "▌"
                self._cur_bubble.update_text(display); updated = True
        if updated: self._scroll_bottom()
        self.after(30, self._poll_tokens)

    def _poll_face(self):
        """Drift the buddy to sleep when idle for a while."""
        try:
            if not (self._is_thinking or self._is_recording):
                idle = time.time() - self._last_interaction
                self._face("sleeping" if idle > 180 else "idle")
        except Exception:
            pass
        self.after(4000, self._poll_face)


def _enable_drag_drop(app: OverlayApp):
    try:
        from tkinterdnd2 import DND_FILES
        app.chat_frame.drop_target_register(DND_FILES)
        app.chat_frame.dnd_bind("<<Drop>>", lambda e: _handle_drop(app, e.data))
        app.input_field.drop_target_register(DND_FILES)
        app.input_field.dnd_bind("<<Drop>>", lambda e: _handle_drop(app, e.data))
        log.info("Drag-drop enabled")
    except ImportError:
        log.info("tkinterdnd2 not installed — drag-drop disabled (pip install tkinterdnd2)")
    except Exception as e:
        log.warning(f"Drag-drop: {e}")

def _handle_drop(app, data):
    path = data.strip().strip("{}")
    if path and os.path.isfile(path):
        app.after(0, lambda: app._send_as_user(f"Read and summarise this file: {path}"))
