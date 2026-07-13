"""
BuddyFace — an animated "screen buddy" robot character.

A friendly little desk robot: light rounded head with a dark screen face,
two glowing eyes and a smile, an antenna with a glowing tip, side ear-rings,
and a rounded body with an "AI" badge. The character floats on a transparent
background (no square frame), and its glow colour tracks Aria's mood via a
callback. Pure tkinter Canvas drawing — no image assets required.

States:
    idle       — eyes open, gentle smile, occasional blink, antenna pulse
    thinking   — eyes narrow and glance side to side
    speaking   — mouth animates open/closed while eyes bob
    listening  — eyes go wide (recording)
    sleeping   — eyes close into arcs, rising "z z z"
"""

import math
import tkinter as tk
from typing import Callable, Optional

# Key colour: painted behind the robot and made transparent by the window, so
# the icon reads as a character, not a square. Near-black (but unused by any
# palette colour) so antialiased edge pixels blend invisibly instead of
# leaving a bright fringe around rounded corners.
KEY_BG    = "#252321"

HEAD      = "#EAEFF7"
HEAD_EDGE = "#C4CDDC"
BODY      = "#DEE5F0"
SCREEN_BG = "#0A0C12"
TICK_MS   = 55


class BuddyFace(tk.Canvas):
    def __init__(self, parent, size: int = 46,
                 get_color: Optional[Callable[[], str]] = None,
                 bg: str = KEY_BG, **kw):
        super().__init__(parent, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0, **kw)
        self._size      = size
        self._get_color = get_color or (lambda: "#4FC3F7")
        self._state     = "idle"
        self._frame     = 0
        self._blink_at  = 30
        self._running   = False

    # ── public API ──────────────────────────────────────────────────────────
    def set_state(self, state: str):
        if state != self._state:
            self._state = state
            self._frame = 0

    def start(self):
        if not self._running:
            self._running = True
            self._tick()

    def stop(self):
        self._running = False

    def resize(self, size: int):
        self._size = size
        self.configure(width=size, height=size)

    # ── animation loop ──────────────────────────────────────────────────────
    def _tick(self):
        if not self._running:
            return
        try:
            self._draw()
        except tk.TclError:
            return  # widget destroyed
        self._frame += 1
        self.after(TICK_MS, self._tick)

    def _draw(self):
        self.delete("all")
        s = self._size
        color = self._get_color()
        cx = s / 2
        f = self._frame
        state = self._state

        # ── Antenna ──
        ball_r = max(2, s * 0.055)
        ball_y = s * 0.11
        pulse  = 0.65 + 0.35 * (0.5 + 0.5 * math.sin(f * 0.15))
        self.create_line(cx, ball_y + ball_r, cx, s * 0.25,
                         fill=self._dim(color, 0.55), width=max(1, int(s / 34)))
        self.create_oval(cx - ball_r, ball_y - ball_r, cx + ball_r, ball_y + ball_r,
                         fill=self._dim(color, pulse), outline="")

        # ── Ears (side rings) ──
        ear_y = s * 0.46
        ear_r = s * 0.085
        for ex in (s * 0.20, s * 0.80):
            self.create_oval(ex - ear_r, ear_y - ear_r, ex + ear_r, ear_y + ear_r,
                             fill=HEAD_EDGE, outline="")
            self.create_oval(ex - ear_r * 0.5, ear_y - ear_r * 0.5,
                             ex + ear_r * 0.5, ear_y + ear_r * 0.5,
                             fill=self._dim(color, 0.9), outline="")

        # ── Body base + AI badge ──
        self._round_rect(s * 0.31, s * 0.60, s * 0.69, s * 0.90, r=s * 0.15,
                         fill=BODY, outline=HEAD_EDGE, width=max(1, s // 48))
        badge_r = s * 0.078
        by = s * 0.76
        self.create_oval(cx - badge_r, by - badge_r, cx + badge_r, by + badge_r,
                         fill=self._dim(color, 0.85), outline="")
        self.create_text(cx, by, text="AI", fill=SCREEN_BG,
                         font=("Inter", max(5, int(s * 0.11)), "bold"))

        # ── Head shell ──
        self._round_rect(s * 0.20, s * 0.23, s * 0.80, s * 0.64, r=s * 0.19,
                         fill=HEAD, outline=HEAD_EDGE, width=max(1, s // 40))

        # ── Face screen ──
        self._round_rect(s * 0.28, s * 0.29, s * 0.72, s * 0.60, r=s * 0.12,
                         fill=SCREEN_BG, outline="")

        # ── Eyes & mouth (state-driven, inside screen) ──
        eye_y  = s * 0.42
        eye_dx = s * 0.105
        eye_w  = s * 0.05
        lx, rx = cx - eye_dx, cx + eye_dx
        mouth_y = s * 0.53

        if state == "sleeping":
            self._closed_eyes(lx, rx, eye_y, eye_w, color)
            self._zzz(s, f, color)
            return

        blinking = False
        if state in ("idle", "speaking"):
            if f >= self._blink_at:
                if f <= self._blink_at + 2:
                    blinking = True
                else:
                    self._blink_at = f + 40 + int(30 * (0.5 + 0.5 * math.sin(f)))

        if state == "listening":
            self._eye_bar(lx, eye_y, eye_w, eye_w * 3.0, color, glow=True)
            self._eye_bar(rx, eye_y, eye_w, eye_w * 3.0, color, glow=True)
            self._smile(cx, mouth_y, s, color, curve=0.5)
        elif state == "thinking":
            g = math.sin(f * 0.18) * s * 0.03
            self._eye_bar(lx + g, eye_y, eye_w, eye_w * 1.6, color)
            self._eye_bar(rx + g, eye_y, eye_w, eye_w * 1.6, color)
        elif blinking:
            self._eye_bar(lx, eye_y, eye_w, max(2, eye_w * 0.3), color)
            self._eye_bar(rx, eye_y, eye_w, max(2, eye_w * 0.3), color)
            self._smile(cx, mouth_y, s, color)
        elif state == "speaking":
            bob = math.sin(f * 0.5) * s * 0.012
            self._eye_bar(lx, eye_y + bob, eye_w, eye_w * 2.3, color, glow=True)
            self._eye_bar(rx, eye_y + bob, eye_w, eye_w * 2.3, color, glow=True)
            self._mouth_open(cx, mouth_y, s, f, color)
        else:  # idle
            breathe = math.sin(f * 0.08) * s * 0.01
            self._eye_bar(lx, eye_y, eye_w, eye_w * 2.3 + breathe, color, glow=True)
            self._eye_bar(rx, eye_y, eye_w, eye_w * 2.3 + breathe, color, glow=True)
            self._smile(cx, mouth_y, s, color)

    # ── drawing helpers ─────────────────────────────────────────────────────
    def _eye_bar(self, ex, cy, w, h, color, glow=False):
        if glow:
            self.create_oval(ex - w * 1.9, cy - h * 0.75, ex + w * 1.9, cy + h * 0.75,
                             fill=self._dim(color, 0.30), outline="")
        self._round_rect(ex - w, cy - h / 2, ex + w, cy + h / 2, r=w,
                         fill=color, outline="")

    def _closed_eyes(self, lx, rx, cy, w, color):
        for ex in (lx, rx):
            self.create_arc(ex - w * 1.6, cy - w, ex + w * 1.6, cy + w,
                            start=200, extent=140, style=tk.ARC,
                            outline=color, width=max(2, int(self._size / 26)))

    def _smile(self, cx, cy, s, color, curve=1.0):
        w = s * 0.085 * curve
        self.create_arc(cx - w, cy - w * 0.5, cx + w, cy + w * 1.1,
                        start=200, extent=140, style=tk.ARC,
                        outline=color, width=max(1, int(s / 32)))

    def _mouth_open(self, cx, cy, s, f, color):
        open_amt = (0.35 + 0.65 * abs(math.sin(f * 0.5))) * s * 0.045
        w = s * 0.06
        self.create_oval(cx - w, cy - open_amt, cx + w, cy + open_amt,
                         fill=color, outline="")

    def _zzz(self, s, f, color):
        base_x = s * 0.70
        for i in range(3):
            phase = (f * 0.03 + i * 0.5) % 1.0
            y = s * 0.34 - phase * s * 0.24
            x = base_x + phase * s * 0.12
            size = int(s * (0.13 + i * 0.03))
            col = self._dim(color, 0.4 + 0.5 * (1 - phase))
            self.create_text(x, y, text="z", fill=col,
                             font=("Inter", max(6, size), "bold"))

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]
        return self.create_polygon(pts, smooth=True, **kw)

    @staticmethod
    def _dim(hex_color: str, factor: float) -> str:
        try:
            h = hex_color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            r, g, b = (min(255, int(c * factor)) for c in (r, g, b))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color
