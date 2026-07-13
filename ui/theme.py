"""
Shared UI theme — Claude-inspired warm dark palette and typography.

Claude's brand fonts (Styrene / Tiempos) are proprietary, so we use the
closest fonts shipped with Windows: Segoe UI for interface text and
Georgia for names/reading text (the serif that gives the "Claude look").
"""

FONT  = "Segoe UI"   # interface sans
SERIF = "Georgia"    # reading serif

C = {
    "bg":       "#262624",   # window / card
    "panel":    "#30302E",   # raised surfaces
    "panel2":   "#373735",   # hover / chips
    "input":    "#3A3A37",   # input fields
    "text":     "#F5F4EF",   # primary ivory text
    "dim":      "#B8B5AD",   # secondary text
    "muted":    "#82807A",   # tertiary text
    "accent":   "#D97757",   # Claude coral
    "accent2":  "#C4633F",   # coral hover
    "accent_s": "#4A3A32",   # soft coral-tinted hover
    "border":   "#3E3D3A",
    "green":    "#8CB07D",
    "red":      "#E5695E",
    "reminder": "#D9A957",
    "code_bg":  "#1F1E1C",
    "code_tx":  "#E0B084",
    # buddy / mic state colours
    "orb_idle": "#D97757",
    "orb_think":"#D9A957",
    "orb_rec":  "#D96D8C",
    "mic_idle": "#3A3A37",
    "mic_on":   "#D96D8C",
    "input_bg": "#3A3A37",
}
