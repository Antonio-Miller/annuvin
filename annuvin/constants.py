"""
constants.py — Shared colours, sizes and enumerations for Annuvin.
"""

# ── Window ────────────────────────────────────────────────────────────────────
WINDOW_WIDTH  = 900
WINDOW_HEIGHT = 700
FPS           = 60
TITLE         = "Annuvin"

# ── Colours ───────────────────────────────────────────────────────────────────
BLACK       = (  0,   0,   0)
WHITE       = (255, 255, 255)
DARK_GREY   = ( 40,  40,  40)
GREY        = (100, 100, 100)
LIGHT_GREY  = (200, 200, 200)
BG_COLOR    = ( 18,  18,  30)   # deep navy background
PANEL_COLOR = ( 28,  28,  48)   # slightly lighter panel
BORDER_COLOR= ( 60,  60, 100)

# Hex board
HEX_FILL        = ( 50,  60,  80)
HEX_BORDER      = ( 80,  90, 120)
HEX_HOVER       = ( 70,  90, 130)
HEX_SELECTED    = ( 50, 130, 200)
HEX_VALID_MOVE  = ( 50, 180,  80)
HEX_LAST_MOVE   = ( 90,  70, 160)

# Players
P1_COLOR        = (220,  80,  80)   # red
P2_COLOR        = ( 80, 180, 220)   # blue
P1_COLOR_DARK   = (160,  40,  40)
P2_COLOR_DARK   = ( 40, 120, 160)

# UI
BUTTON_COLOR        = ( 60,  80, 140)
BUTTON_HOVER_COLOR  = ( 80, 110, 190)
BUTTON_DISABLED     = ( 50,  50,  70)
BUTTON_TEXT         = WHITE
ACCENT_COLOR        = (180, 140,  60)
TEXT_COLOR          = (220, 220, 240)
DIM_TEXT_COLOR      = (130, 130, 160)

# ── Board geometry ────────────────────────────────────────────────────────────
BOARD_SIZE = 4          # HexHex-4: 4 hexes on each side
HEX_RADIUS = 36         # pixel radius of each hex cell

# ── Players ───────────────────────────────────────────────────────────────────
PLAYER_1 = 1
PLAYER_2 = 2

# ── Game states ───────────────────────────────────────────────────────────────
class GameState:
    MENU        = "menu"
    PLAYING     = "playing"
    GAME_OVER   = "game_over"
    RULES       = "rules"
    SETTINGS    = "settings"

# ── Game modes ────────────────────────────────────────────────────────────────
class GameMode:
    HUMAN_VS_HUMAN = "human_vs_human"
    HUMAN_VS_AI    = "human_vs_ai"
    AI_VS_AI       = "ai_vs_ai"
