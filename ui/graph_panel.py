"""
Memory Graph viewer — a visual node/edge map of Aria's knowledge graph.

Entities are nodes (coloured by type), relations are labelled edges. A light
force-directed layout spreads them out. Click a node to see its observations;
delete a node from there.
"""

import math
import random
import tkinter as tk

import customtkinter as ctk

import config as cfg
from ui.theme import C, FONT, SERIF
from core.knowledge_graph import get_graph, delete_entity

_TYPE_COLORS = {
    "person": "#D97757", "project": "#8CB07D", "device": "#D9A957",
    "place": "#7DA7C4", "organization": "#C48CB0", "preference": "#D96D8C",
    "event": "#B0A87D", "concept": "#82807A", "skill": "#7DC4B0",
}


class GraphPanel(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title(f"{cfg.get('assistant_name')} — Memory Graph")
        self.geometry("780x660")
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self._selected = None
        self._build()
        self.after(120, self._render)

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(hdr, text="🕸  Memory Graph", font=(SERIF, 15, "bold"),
                     text_color=C["text"]).pack(side="left")
        ctk.CTkButton(hdr, text="⟳ Refresh", width=80, height=26,
                      fg_color=C["panel2"], hover_color=C["accent_s"],
                      text_color=C["dim"], font=(FONT, 11), corner_radius=13,
                      command=self._render).pack(side="right")

        self._canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0)
        self._canvas.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        self._canvas.bind("<Configure>", lambda e: self._render())

        self._info = ctk.CTkFrame(self, fg_color=C["panel"], corner_radius=10, height=110)
        self._info.pack(fill="x", padx=12, pady=(0, 12)); self._info.pack_propagate(False)
        self._info_lbl = ctk.CTkLabel(
            self._info, text="Click a node to see what Aria remembers about it.",
            font=(FONT, 11), text_color=C["dim"], anchor="nw", justify="left",
            wraplength=720)
        self._info_lbl.pack(fill="both", expand=True, padx=12, pady=8)

    # ── layout ────────────────────────────────────────────────────────────
    def _layout(self, names, edges, w, h):
        if not names:
            return {}
        random.seed(42)
        pos = {n: [random.uniform(w * 0.25, w * 0.75),
                   random.uniform(h * 0.25, h * 0.75)] for n in names}
        for _ in range(min(200, 60 + len(names) * 8)):
            disp = {n: [0.0, 0.0] for n in names}
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    dx = pos[a][0] - pos[b][0]
                    dy = pos[a][1] - pos[b][1]
                    d2 = dx * dx + dy * dy + 0.01
                    f = 9000.0 / d2
                    disp[a][0] += dx * f; disp[a][1] += dy * f
                    disp[b][0] -= dx * f; disp[b][1] -= dy * f
            for a, b in edges:
                if a not in pos or b not in pos:
                    continue
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                d = math.hypot(dx, dy) + 0.01
                f = (d - 130) * 0.02
                disp[a][0] -= dx / d * f * d; disp[a][1] -= dy / d * f * d
                disp[b][0] += dx / d * f * d; disp[b][1] += dy / d * f * d
            for n in names:
                pos[n][0] = min(w - 70, max(70, pos[n][0] + max(-18, min(18, disp[n][0]))))
                pos[n][1] = min(h - 60, max(50, pos[n][1] + max(-18, min(18, disp[n][1]))))
        return pos

    def _render(self):
        cv = self._canvas
        cv.delete("all")
        g = get_graph()
        ents = g["entities"]
        if not ents:
            cv.create_text(360, 200, text="No memories yet — chat with Aria and\n"
                           "the graph will build itself.", fill=C["muted"],
                           font=(FONT, 12), justify="center")
            return
        w = max(cv.winfo_width(), 400)
        h = max(cv.winfo_height(), 300)
        names = [e["name"] for e in ents]
        by_name = {e["name"]: e for e in ents}
        edges = [(r["src"], r["dst"]) for r in g["relations"]]
        pos = self._layout(names, edges, w, h)

        # edges
        for r in g["relations"]:
            a, b = r["src"], r["dst"]
            if a in pos and b in pos:
                x1, y1 = pos[a]; x2, y2 = pos[b]
                cv.create_line(x1, y1, x2, y2, fill=C["border"], width=1)
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                cv.create_text(mx, my, text=r["rel"], fill=C["muted"],
                               font=(FONT, 8))

        # nodes
        for e in ents:
            n = e["name"]
            if n not in pos:
                continue
            x, y = pos[n]
            color = _TYPE_COLORS.get(e["type"], C["muted"])
            rr = 8 + min(10, len(e["observations"]) * 2)
            tag = f"node_{e['id']}"
            cv.create_oval(x - rr, y - rr, x + rr, y + rr, fill=color,
                           outline=C["text"] if self._selected == n else color,
                           width=2, tags=tag)
            label = n if len(n) <= 22 else n[:21] + "…"
            cv.create_text(x, y + rr + 9, text=label, fill=C["text"],
                           font=(FONT, 9, "bold"), tags=tag)
            cv.tag_bind(tag, "<Button-1>", lambda ev, nm=n: self._select(nm, by_name))

    def _select(self, name, by_name):
        self._selected = name
        e = by_name.get(name, {})
        obs = e.get("observations", [])
        g = get_graph()
        rels = [f"{r['src']} —{r['rel']}→ {r['dst']}"
                for r in g["relations"] if name in (r["src"], r["dst"])]
        txt = f"● {name}   [{e.get('type','concept')}]\n"
        if obs:
            txt += "\n".join(f"  • {o}" for o in obs[:5])
        else:
            txt += "  (no observations)"
        if rels:
            txt += "\n  ↔ " + "   ".join(rels[:4])
        self._info_lbl.configure(text=txt)
        self._draw_delete(name)
        self._render()

    def _draw_delete(self, name):
        for w in self._info.winfo_children():
            if isinstance(w, ctk.CTkButton):
                w.destroy()
        ctk.CTkButton(self._info, text="✕ forget", width=70, height=24,
                      fg_color="transparent", hover_color=C["red"],
                      text_color=C["muted"], font=(FONT, 10),
                      command=lambda: self._forget(name)).place(relx=1.0, x=-8, y=8,
                                                                anchor="ne")

    def _forget(self, name):
        delete_entity(name)
        self._selected = None
        self._info_lbl.configure(text=f"Forgot '{name}'.")
        for w in self._info.winfo_children():
            if isinstance(w, ctk.CTkButton):
                w.destroy()
        self._render()
