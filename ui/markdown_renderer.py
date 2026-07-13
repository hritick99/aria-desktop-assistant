"""
Markdown renderer for CustomTkinter.
MarkdownBubble is a drop-in for plain message bubbles.
Streaming-safe: update_text() only rebuilds if content changed significantly.

Claude-style layout: user messages sit in a quiet rounded bubble on the
right; assistant messages render as plain serif text on the background.
"""
import re
import customtkinter as ctk
import tkinter as tk
from typing import List, Tuple

from ui.theme import C, FONT, SERIF

MONO = "Consolas"


def _set_clipboard_win(text: str) -> bool:
    """Write the clipboard via the Win32 API. Tk's clipboard_append uses
    delayed rendering, which Win+V clipboard history never sees — this
    renders immediately. Returns False on any failure (caller falls back)."""
    import os
    if os.name != "nt":
        return False
    try:
        import ctypes
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        if not u32.OpenClipboard(0):
            return False
        try:
            u32.EmptyClipboard()
            data = text.encode("utf-16-le") + b"\x00\x00"
            h = k32.GlobalAlloc(0x0042, len(data))  # GMEM_MOVEABLE|GMEM_ZEROINIT
            p = k32.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            k32.GlobalUnlock(h)
            u32.SetClipboardData(13, h)             # CF_UNICODETEXT
        finally:
            u32.CloseClipboard()
        return True
    except Exception:
        return False

def _tokenise(text: str) -> List[Tuple[str, str]]:
    tokens = []; lines = text.split("\n"); in_code = False; code_lines = []
    for line in lines:
        if line.strip().startswith("```"):
            if in_code: tokens.append(("code_block", "\n".join(code_lines))); code_lines = []; in_code = False
            else: in_code = True
            continue
        if in_code: code_lines.append(line); continue
        if line.startswith("### "):   tokens.append(("h3", line[4:]))
        elif line.startswith("## "):  tokens.append(("h2", line[3:]))
        elif line.startswith("# "):   tokens.append(("h1", line[2:]))
        elif re.match(r'^---+$', line.strip()): tokens.append(("sep", ""))
        elif re.match(r'^[-*•]\s+', line):      tokens.append(("bullet", re.sub(r'^[-*•]\s+','',line)))
        elif re.match(r'^\d+\.\s+', line):      tokens.append(("numbered", re.sub(r'^\d+\.\s+','',line)))
        elif line.strip() == "":                tokens.append(("blank", ""))
        else:                                   tokens.append(("text", line))
    if in_code and code_lines: tokens.append(("code_block", "\n".join(code_lines)))
    return tokens

def _inline(parent, text: str, wrap: int):
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    for part in re.split(r'(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)', text):
        if not part: continue
        if part.startswith("`") and part.endswith("`"):
            ctk.CTkLabel(frame, text=f" {part[1:-1]} ", font=(MONO,11),
                         text_color=C["code_tx"], fg_color=C["code_bg"],
                         corner_radius=4).pack(side="left", padx=1)
        elif part.startswith("**") and part.endswith("**"):
            ctk.CTkLabel(frame, text=part[2:-2], font=(SERIF,12,"bold"),
                         text_color=C["text"], wraplength=wrap).pack(side="left")
        elif part.startswith("*") and part.endswith("*"):
            ctk.CTkLabel(frame, text=part[1:-1], font=(SERIF,12,"italic"),
                         text_color=C["dim"], wraplength=wrap).pack(side="left")
        elif part.strip():
            ctk.CTkLabel(frame, text=part, font=(SERIF,12), text_color=C["text"],
                         wraplength=wrap, justify="left", anchor="w").pack(side="left", fill="x")
    return frame

_HAS_MD = re.compile(r'\*\*|`|^#|^-\s|^•\s|^```', re.M)

class MarkdownBubble(ctk.CTkFrame):
    def __init__(self, parent, role, content, timestamp="", wrap_width=340,
                 lite=False, **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        import config as cfg
        is_user = role == "user"
        self._wrap = wrap_width
        self._last_content = None
        self._raw = content

        # Lite mode: a single plain-text label, no markdown parse, no copy
        # button, no right-click menus. Used for reloading history fast.
        if lite:
            self._bubble = ctk.CTkFrame(
                self, fg_color=C["panel2"] if is_user else "transparent",
                corner_radius=14 if is_user else 0)
            self._bubble.pack(anchor="e" if is_user else "w",
                              fill=None if is_user else "x", padx=6, pady=(2,4))
            ctk.CTkLabel(self._bubble, text=content, font=(SERIF,12),
                         text_color=C["text"], wraplength=wrap_width,
                         justify="left", anchor="w").pack(padx=10, pady=6, fill="x")
            return

        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=6, pady=(6,0))
        label_text = cfg.get('user_name') if is_user else cfg.get('assistant_name')
        ctk.CTkLabel(hdr, text=label_text, font=(FONT,10,"bold"),
                     text_color=C["accent"] if is_user else C["dim"]
                     ).pack(side="right" if is_user else "left")
        self._copy_btn = ctk.CTkButton(hdr, text="⧉", width=24, height=18,
                                       fg_color="transparent", hover_color=C["panel2"],
                                       text_color=C["muted"], font=(FONT,10),
                                       command=self._copy_all)
        self._copy_btn.pack(side="left" if is_user else "right", padx=2)
        if timestamp:
            ctk.CTkLabel(hdr, text=timestamp, font=(FONT,9),
                         text_color=C["muted"]).pack(side="left" if is_user else "right", padx=6)

        if is_user:
            self._bubble = ctk.CTkFrame(self, fg_color=C["panel2"], corner_radius=14)
            self._bubble.pack(anchor="e", padx=6, pady=(2,4), ipadx=4)
        else:
            self._bubble = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
            self._bubble.pack(fill="x", anchor="w", padx=6, pady=(2,4))
        self._render(content)

    # ── clipboard ────────────────────────────────────────────────────────
    def _copy(self, text: str):
        if not _set_clipboard_win(text):
            self.clipboard_clear(); self.clipboard_append(text)
        self._copy_btn.configure(text="✓", text_color=C["green"])
        self.after(1200, lambda: self._copy_btn.configure(text="⧉", text_color=C["muted"]))

    def _copy_all(self):
        self._copy(self._raw)

    def _show_menu(self, event, code=None):
        m = tk.Menu(self, tearoff=0, bg=C["panel"], fg=C["text"], bd=0,
                    activebackground=C["accent"], activeforeground=C["bg"])
        if code is not None:
            m.add_command(label="Copy code", command=lambda: self._copy(code))
        m.add_command(label="Copy message", command=self._copy_all)
        m.tk_popup(event.x_root, event.y_root)
        return "break"

    def _bind_menu(self, widget, code=None):
        widget.bind("<Button-3>", lambda e: self._show_menu(e, code))
        for ch in widget.winfo_children():
            self._bind_menu(ch, code)

    def _render(self, content: str):
        self._raw = content
        for w in self._bubble.winfo_children(): w.destroy()
        # Fast path for plain text
        if not _HAS_MD.search(content):
            ctk.CTkLabel(self._bubble, text=content, font=(SERIF,12), text_color=C["text"],
                         wraplength=self._wrap, justify="left", anchor="w").pack(padx=10,pady=6,fill="x")
            self._bind_menu(self._bubble)
            return
        tokens = _tokenise(content)
        self._code_blocks = []
        box = ctk.CTkFrame(self._bubble, fg_color="transparent")
        box.pack(padx=8, pady=6, fill="x")
        for typ, val in tokens:
            if typ == "h1":
                ctk.CTkLabel(box, text=val, font=(SERIF,16,"bold"), text_color=C["text"],
                             anchor="w").pack(fill="x", pady=(6,2))
            elif typ == "h2":
                ctk.CTkLabel(box, text=val, font=(SERIF,14,"bold"), text_color=C["text"],
                             anchor="w").pack(fill="x", pady=(4,2))
            elif typ == "h3":
                ctk.CTkLabel(box, text=val, font=(SERIF,12,"bold"), text_color=C["text"],
                             anchor="w").pack(fill="x", pady=(2,1))
            elif typ == "code_block":
                f = ctk.CTkFrame(box, fg_color=C["code_bg"], corner_radius=8)
                f.pack(fill="x", pady=4)
                ctk.CTkLabel(f, text=val, font=(MONO,11), text_color=C["code_tx"],
                             justify="left", anchor="w", wraplength=self._wrap).pack(padx=10,pady=8,fill="x")
                self._code_blocks.append((f, val))
            elif typ == "bullet":
                row = ctk.CTkFrame(box, fg_color="transparent"); row.pack(fill="x", pady=1)
                ctk.CTkLabel(row, text="•", font=(SERIF,12,"bold"),
                             text_color=C["accent"], width=16).pack(side="left")
                _inline(row, val, self._wrap-20).pack(side="left", fill="x", expand=True)
            elif typ == "numbered":
                row = ctk.CTkFrame(box, fg_color="transparent"); row.pack(fill="x", pady=1)
                ctk.CTkLabel(row, text="›", font=(SERIF,12), text_color=C["accent"], width=16).pack(side="left")
                _inline(row, val, self._wrap-20).pack(side="left", fill="x", expand=True)
            elif typ == "sep":
                ctk.CTkFrame(box, fg_color=C["border"], height=1).pack(fill="x", pady=6)
            elif typ == "text" and val.strip():
                _inline(box, val, self._wrap).pack(fill="x", pady=1)
            elif typ == "blank":
                ctk.CTkFrame(box, fg_color="transparent", height=4).pack()
        self._bind_menu(self._bubble)
        for f, code in self._code_blocks:
            self._bind_menu(f, code)

    def update_text(self, content: str):
        # Only re-render if content changed meaningfully (avoids flicker every token during plain text)
        if self._last_content is not None:
            # During streaming: only do full re-render if markdown detected
            if not _HAS_MD.search(content):
                # Update label in place
                children = self._bubble.winfo_children()
                if children and isinstance(children[0], ctk.CTkLabel):
                    children[0].configure(text=content)
                    self._last_content = content; self._raw = content
                    return
        self._last_content = content
        self._render(content)
