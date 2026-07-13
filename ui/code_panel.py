"""
Code Workspace — build, edit, and RUN projects with Claude Code or Aider.

A dedicated window (separate from chat): pick a project folder, choose the
engine, describe a change, and Aria applies it against the repo. A file list
shows the project (recently-changed files highlighted, click to open), and a
Run button executes the project and streams its output into the log.
"""

import os
import subprocess
import threading
import time

import customtkinter as ctk
from tkinter import filedialog

import config as cfg
from ui.theme import C, FONT, SERIF
from core.logger import get_logger

log = get_logger("code_panel")

_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".idea",
         ".vscode", "dist", "build", ".pytest_cache", ".mypy_cache"}
_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class CodePanel(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title(f"{cfg.get('assistant_name')} — Code Workspace")
        self.geometry("660x780")
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self._busy = False
        self._proc = None
        self._build()
        if cfg.get("code_project_dir"):
            self._refresh_files()
            self._detect_run_cmd()

    # ── layout ────────────────────────────────────────────────────────────
    def _build(self):
        ctk.CTkLabel(self, text="⌨  Code Workspace", font=(SERIF, 16, "bold"),
                     text_color=C["text"]).pack(pady=(12, 2))
        ctk.CTkLabel(self, text="Build, edit & run projects with Claude Code or Aider",
                     font=(FONT, 10), text_color=C["dim"]).pack(pady=(0, 8))

        top = ctk.CTkFrame(self, fg_color=C["panel"], corner_radius=10)
        top.pack(fill="x", padx=14, pady=(0, 6))

        r1 = ctk.CTkFrame(top, fg_color="transparent")
        r1.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkLabel(r1, text="Project", font=(FONT, 11), text_color=C["dim"],
                     width=52, anchor="w").pack(side="left")
        self._dir = ctk.CTkEntry(r1, height=30, fg_color=C["input"],
                                 border_color=C["border"], text_color=C["text"],
                                 font=(FONT, 11), placeholder_text="pick or create a folder")
        self._dir.pack(side="left", fill="x", expand=True, padx=6)
        if cfg.get("code_project_dir"):
            self._dir.insert(0, cfg.get("code_project_dir"))
        ctk.CTkButton(r1, text="Browse", width=60, height=30, fg_color=C["panel2"],
                      hover_color=C["accent_s"], text_color=C["dim"], font=(FONT, 11),
                      corner_radius=8, command=self._browse).pack(side="left", padx=(0, 2))
        ctk.CTkButton(r1, text="New", width=44, height=30, fg_color=C["panel2"],
                      hover_color=C["accent_s"], text_color=C["dim"], font=(FONT, 11),
                      corner_radius=8, command=self._new_project).pack(side="left")

        r2 = ctk.CTkFrame(top, fg_color="transparent")
        r2.pack(fill="x", padx=10, pady=(4, 10))
        ctk.CTkLabel(r2, text="Engine", font=(FONT, 11), text_color=C["dim"],
                     width=52, anchor="w").pack(side="left")
        self._engine = ctk.StringVar(
            value="Claude Code" if cfg.get("code_backend") == "claude_code" else "Aider")
        ctk.CTkOptionMenu(r2, variable=self._engine, values=["Claude Code", "Aider"],
                          width=150, height=30, fg_color=C["input"],
                          button_color=C["accent"], button_hover_color=C["accent2"],
                          dropdown_fg_color=C["panel"], font=(FONT, 11)).pack(side="left", padx=6)
        ctk.CTkLabel(r2, text=self._engine_status(), font=(FONT, 9),
                     text_color=C["muted"], anchor="w").pack(side="left", padx=4)

        # Instruction + Build
        self._instr = ctk.CTkTextbox(self, height=72, fg_color=C["input"],
                                     border_color=C["border"], border_width=1,
                                     text_color=C["text"], font=(FONT, 12), wrap="word")
        self._instr.pack(fill="x", padx=14, pady=(2, 0))
        self._instr.bind("<Control-Return>", lambda e: (self._run_build(), "break"))
        rb = ctk.CTkFrame(self, fg_color="transparent")
        rb.pack(fill="x", padx=14, pady=(6, 4))
        self._build_btn = ctk.CTkButton(rb, text="Build  ▸", width=110, height=32,
                                        fg_color=C["accent"], hover_color=C["accent2"],
                                        text_color=C["bg"], font=(FONT, 12, "bold"),
                                        corner_radius=16, command=self._run_build)
        self._build_btn.pack(side="right")
        ctk.CTkLabel(rb, text="describe a change, then Build (Ctrl+Enter)",
                     font=(FONT, 9), text_color=C["muted"]).pack(side="right", padx=8)

        # Middle: files (left) + output (right)
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.pack(fill="both", expand=True, padx=14, pady=(2, 4))

        left = ctk.CTkFrame(mid, fg_color="transparent", width=200)
        left.pack(side="left", fill="y", padx=(0, 6)); left.pack_propagate(False)
        fh = ctk.CTkFrame(left, fg_color="transparent"); fh.pack(fill="x")
        ctk.CTkLabel(fh, text="Files", font=(FONT, 11), text_color=C["dim"],
                     anchor="w").pack(side="left")
        ctk.CTkButton(fh, text="⟳", width=24, height=20, fg_color="transparent",
                      hover_color=C["panel2"], text_color=C["muted"], font=(FONT, 11),
                      command=self._refresh_files).pack(side="right")
        self._files = ctk.CTkScrollableFrame(left, fg_color=C["panel"], corner_radius=8)
        self._files.pack(fill="both", expand=True, pady=(2, 0))

        right = ctk.CTkFrame(mid, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(right, text="Output", font=(FONT, 11), text_color=C["dim"],
                     anchor="w").pack(fill="x")
        self._out = ctk.CTkTextbox(right, fg_color=C["code_bg"], text_color=C["code_tx"],
                                   font=("Consolas", 10), wrap="word")
        self._out.pack(fill="both", expand=True, pady=(2, 0))
        self._out.insert("end", "Ready. Pick a folder, describe a change, hit Build. "
                                "Use Run to execute the project.\n")
        self._out.configure(state="disabled")

        # Run row
        run = ctk.CTkFrame(self, fg_color="transparent")
        run.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkLabel(run, text="Run", font=(FONT, 11), text_color=C["dim"],
                     width=32, anchor="w").pack(side="left")
        self._runcmd = ctk.CTkEntry(run, height=30, fg_color=C["input"],
                                    border_color=C["border"], text_color=C["text"],
                                    font=("Consolas", 11),
                                    placeholder_text="e.g. python main.py")
        self._runcmd.pack(side="left", fill="x", expand=True, padx=6)
        self._run_btn = ctk.CTkButton(run, text="Run  ▶", width=90, height=30,
                                      fg_color=C["green"], hover_color=C["accent2"],
                                      text_color=C["bg"], font=(FONT, 12, "bold"),
                                      corner_radius=15, command=self._run_project)
        self._run_btn.pack(side="left")
        self._stop_btn = ctk.CTkButton(run, text="■", width=34, height=30,
                                       fg_color=C["panel2"], hover_color=C["red"],
                                       text_color=C["dim"], font=(FONT, 12),
                                       corner_radius=15, command=self._stop_project)
        self._stop_btn.pack(side="left", padx=(4, 0))

    # ── helpers ───────────────────────────────────────────────────────────
    def _engine_status(self):
        try:
            from core.aider_integration import available as ai
            from core.claude_code_integration import available as cc
            return f"(Claude Code: {'ready' if cc() else 'no'}, Aider: {'ready' if ai() else 'no'})"
        except Exception:
            return ""

    def _folder(self):
        return self._dir.get().strip().strip('"')

    def _browse(self):
        d = filedialog.askdirectory(title="Choose a project folder")
        if d:
            self._dir.delete(0, "end"); self._dir.insert(0, d)
            cfg.set("code_project_dir", d)
            self._refresh_files(); self._detect_run_cmd()
        self.lift(); self.focus_force()

    def _new_project(self):
        base = filedialog.askdirectory(title="Where to create the new project folder?")
        self.lift(); self.focus_force()
        if not base:
            return
        dlg = ctk.CTkInputDialog(text="New project folder name:", title="New Project")
        name = dlg.get_input()
        if not name:
            return
        path = os.path.join(base, name.strip())
        try:
            os.makedirs(path, exist_ok=True)
            subprocess.run(["git", "init"], cwd=path, capture_output=True,
                           creationflags=_CREATE_NO_WINDOW)
            self._dir.delete(0, "end"); self._dir.insert(0, path)
            cfg.set("code_project_dir", path)
            self._append(f"Created project: {path}\n"); self._refresh_files()
        except Exception as e:
            self._append(f"Could not create project: {e}\n")

    def _iter_files(self, root):
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in _SKIP and not d.startswith(".")]
            for fn in fns:
                yield os.path.join(dp, fn)
            if dp.count(os.sep) - root.count(os.sep) >= 3:
                dns[:] = []

    def _refresh_files(self):
        for w in self._files.winfo_children():
            w.destroy()
        root = self._folder()
        if not root or not os.path.isdir(root):
            return
        now = time.time()
        items = []
        for p in self._iter_files(root):
            try:
                items.append((os.path.relpath(p, root), p, os.path.getmtime(p)))
            except OSError:
                continue
        items.sort(key=lambda t: t[0].lower())
        if not items:
            ctk.CTkLabel(self._files, text="(empty)", font=(FONT, 10),
                         text_color=C["muted"]).pack(pady=8)
            return
        for rel, full, mtime in items[:200]:
            recent = (now - mtime) < 90
            b = ctk.CTkButton(self._files, text=("● " if recent else "") + rel,
                              anchor="w", height=22, corner_radius=5,
                              fg_color="transparent", hover_color=C["panel2"],
                              text_color=C["accent"] if recent else C["dim"],
                              font=(FONT, 10),
                              command=lambda f=full: self._open_file(f))
            b.pack(fill="x", padx=2, pady=1)

    def _open_file(self, path):
        try:
            os.startfile(path)
        except Exception as e:
            self._append(f"Can't open {path}: {e}\n")

    def _detect_run_cmd(self):
        root = self._folder()
        if not root or not os.path.isdir(root):
            return
        guess = ""
        for name in ("main.py", "app.py", "run.py", "__main__.py"):
            if os.path.isfile(os.path.join(root, name)):
                guess = f"python {name}"; break
        if not guess and os.path.isfile(os.path.join(root, "package.json")):
            guess = "npm start"
        if not guess:
            pys = [f for f in os.listdir(root) if f.endswith(".py")]
            if len(pys) == 1:
                guess = f"python {pys[0]}"
        if guess and not self._runcmd.get().strip():
            self._runcmd.delete(0, "end"); self._runcmd.insert(0, guess)

    # ── build ─────────────────────────────────────────────────────────────
    def _run_build(self):
        if self._busy:
            return
        folder, instr = self._folder(), self._instr.get("1.0", "end").strip()
        if not folder or not os.path.isdir(folder):
            self._append("⚠️ Pick a valid project folder first.\n"); return
        if not instr:
            self._append("⚠️ Type what you want built or changed.\n"); return
        cfg.set("code_project_dir", folder)
        cfg.set("code_backend",
                "claude_code" if self._engine.get() == "Claude Code" else "aider")
        self._busy = True
        self._build_btn.configure(state="disabled", text="Working…")
        self._append(f"\n$ [{self._engine.get()}]  {instr}\n")

        def work():
            from core.code_edit import run as run_code_edit
            try:
                res = run_code_edit(f"{folder} | {instr}")
            except Exception as e:
                res = f"Error: {e}"
            try:
                self.after(0, lambda: self._build_done(res))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _build_done(self, res):
        self._append((res or "(no output)") + "\n")
        self._busy = False
        self._build_btn.configure(state="normal", text="Build  ▸")
        self._refresh_files()
        self._detect_run_cmd()

    # ── run project ───────────────────────────────────────────────────────
    def _run_project(self):
        if self._proc is not None:
            self._append("Already running — press ■ to stop first.\n"); return
        folder, cmd = self._folder(), self._runcmd.get().strip()
        if not folder or not os.path.isdir(folder):
            self._append("⚠️ Pick a valid project folder first.\n"); return
        if not cmd:
            self._append("⚠️ Enter a run command (e.g. python main.py).\n"); return
        self._append(f"\n▶ {cmd}\n")
        self._run_btn.configure(state="disabled")

        def work():
            try:
                self._proc = subprocess.Popen(
                    cmd, cwd=folder, shell=True, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, bufsize=1,
                    creationflags=_CREATE_NO_WINDOW)
                for line in self._proc.stdout:
                    self.after(0, lambda l=line: self._append(l))
                code = self._proc.wait()
                self.after(0, lambda: self._append(f"[exited {code}]\n"))
            except Exception as e:
                self.after(0, lambda: self._append(f"Run error: {e}\n"))
            finally:
                self._proc = None
                try:
                    self.after(0, lambda: self._run_btn.configure(state="normal"))
                    self.after(0, self._refresh_files)
                except Exception:
                    pass
        threading.Thread(target=work, daemon=True).start()

    def _stop_project(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._append("[stopped]\n")
            except Exception as e:
                self._append(f"Stop error: {e}\n")

    def _append(self, text):
        self._out.configure(state="normal")
        self._out.insert("end", text)
        self._out.see("end")
        self._out.configure(state="disabled")
