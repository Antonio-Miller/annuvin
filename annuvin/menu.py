"""
menu.py — Main menu and in-game save/load dialogs for Annuvin.

Screens managed here:
  • MainMenu           — title screen with mode buttons
  • PlayerNameScreen   — collect names before Human vs Human game
    • AISkillScreen      — choose AI difficulty before Human vs AI game
  • SaveLoadDialog     — file chooser for saving / loading game state
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional, Tuple

import pygame

from annuvin.constants import (
    WINDOW_WIDTH, WINDOW_HEIGHT,
    BG_COLOR, PANEL_COLOR, BORDER_COLOR,
    TEXT_COLOR, DIM_TEXT_COLOR, ACCENT_COLOR, WHITE, BLACK,
    BUTTON_COLOR, BUTTON_HOVER_COLOR, BUTTON_DISABLED, BUTTON_TEXT,
    P1_COLOR, P2_COLOR,
    GameMode,
)


# ─── Generic helpers ──────────────────────────────────────────────────────────

class _Button:
    """Simple rectangular button."""

    def __init__(self, rect: pygame.Rect, text: str,
                 enabled: bool = True,
                 color: Tuple[int, int, int] = BUTTON_COLOR,
                 hover_color: Tuple[int, int, int] = BUTTON_HOVER_COLOR,
                 font_size: int = 20) -> None:
        self.rect       = rect
        self.text       = text
        self.enabled    = enabled
        self.color      = color
        self.hover_color= hover_color
        self._hovered   = False
        pygame.font.init()
        self._font = pygame.font.SysFont("segoeui", font_size, bold=True)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.enabled:
            return False
        if event.type == pygame.MOUSEMOTION:
            self._hovered = self.rect.collidepoint(event.pos)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                return True
        return False

    def draw(self, surface: pygame.Surface) -> None:
        if not self.enabled:
            pygame.draw.rect(surface, BUTTON_DISABLED, self.rect, border_radius=10)
            label = self._font.render(self.text, True, DIM_TEXT_COLOR)
        else:
            col = self.hover_color if self._hovered else self.color
            pygame.draw.rect(surface, col, self.rect, border_radius=10)
            label = self._font.render(self.text, True, BUTTON_TEXT)
        surface.blit(label, label.get_rect(center=self.rect.center))

    def update_hover(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEMOTION:
            self._hovered = self.rect.collidepoint(event.pos)


# ─── Main Menu ────────────────────────────────────────────────────────────────

class MainMenu:
    """
    Title / main menu screen.

    Buttons:
      • Human vs Human    — active
      • Human vs AI       — disabled (greyed out, "Coming soon")
      • AI vs AI          — disabled (greyed out, "Coming soon")
      • Rules             — opens the rules screen
      • Load Game         — load a saved board position from file
      • Quit              — exit the application

    Callbacks (set by main.py):
      on_human_vs_human()
      on_rules()
      on_load_game()
      on_quit()
    """

    _BTN_W  = 340
    _BTN_H  = 54
    _GAP    = 16

    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface

        pygame.font.init()
        self.font_title    = pygame.font.SysFont("segoeui", 56, bold=True)
        self.font_subtitle = pygame.font.SysFont("segoeui", 20)
        self.font_footer   = pygame.font.SysFont("segoeui", 13)

        # Compute button column
        bx = WINDOW_WIDTH // 2 - self._BTN_W // 2
        by_start = 220

        def mk(label: str, enabled: bool = True, y_offset: int = 0) -> _Button:
            y = by_start + y_offset
            return _Button(
                pygame.Rect(bx, y, self._BTN_W, self._BTN_H),
                label, enabled=enabled,
            )

        step = self._BTN_H + self._GAP
        self.btn_hvh   = mk("Human vs Human",          enabled=True,  y_offset=0 * step)
        self.btn_hvai  = mk("Human vs AI (in development...)",  enabled=True, y_offset=1 * step)
        self.btn_aiai  = mk("AI vs AI  (coming…)",     enabled=False, y_offset=2 * step)
        self.btn_rules = mk("Rules",                   enabled=True,  y_offset=3 * step + 12)
        self.btn_load  = mk("Load Game",               enabled=True,  y_offset=4 * step + 12)
        self.btn_quit  = mk("Quit",                    enabled=True,  y_offset=5 * step + 20,
                            )

        self._buttons: List[_Button] = [
            self.btn_hvh, self.btn_hvai, self.btn_aiai,
            self.btn_rules, self.btn_load, self.btn_quit,
        ]

        # Callbacks
        self.on_human_vs_human: Optional[Callable] = None
        self.on_rules:          Optional[Callable] = None
        self.on_load_game:      Optional[Callable] = None
        self.on_quit:           Optional[Callable] = None

        # Background animation counter
        self._tick = 0

    def handle_event(self, event: pygame.event.Event) -> None:
        for btn in self._buttons:
            btn.update_hover(event)

        if self.btn_hvh.handle_event(event) and self.on_human_vs_human:
            self.on_human_vs_human()
        if self.btn_hvai.handle_event(event) and self.on_human_vs_ai:  # ← ADD THIS
            self.on_human_vs_ai()
        if self.btn_rules.handle_event(event) and self.on_rules:   # ← ADD BEFORE THIS
            self.on_rules()
        if self.btn_load.handle_event(event) and self.on_load_game:
            self.on_load_game()
        if self.btn_quit.handle_event(event) and self.on_quit:
            self.on_quit()

    def update(self) -> None:
        self._tick += 1
        self.surface.fill(BG_COLOR)
        self._draw_background()
        self._draw_title()
        for btn in self._buttons:
            btn.draw(self.surface)
        self._draw_disabled_labels()
        self._draw_footer()

    # ── Visual details ────────────────────────────────────────────────────────

    def _draw_background(self) -> None:
        """Subtle animated hex-dot pattern for visual interest."""
        import math
        dot_color = (30, 35, 60)
        spacing = 52
        offset_x = (self._tick // 3) % spacing
        for x in range(-spacing, WINDOW_WIDTH + spacing, spacing):
            for y in range(-spacing, WINDOW_HEIGHT + spacing, spacing):
                pygame.draw.circle(self.surface, dot_color,
                                   ((x + offset_x) % WINDOW_WIDTH, y), 2)

    def _draw_title(self) -> None:
        # Outer glow effect (draw offset copies)
        glow_surf = self.font_title.render("ANNUVIN", True, (60, 40, 20))
        cx = WINDOW_WIDTH // 2
        for dx, dy in [(-2, 2), (2, 2), (-2, -2), (2, -2)]:
            self.surface.blit(glow_surf, glow_surf.get_rect(center=(cx + dx, 100 + dy)))

        # Main title
        title_surf = self.font_title.render("ANNUVIN", True, ACCENT_COLOR)
        self.surface.blit(title_surf, title_surf.get_rect(center=(cx, 100)))

        # Subtitle
        sub = self.font_subtitle.render(
            "An Abstract Strategy Game for Two Players", True, DIM_TEXT_COLOR)
        self.surface.blit(sub, sub.get_rect(center=(cx, 150)))

        # Divider
        pygame.draw.line(self.surface, BORDER_COLOR,
                         (cx - 170, 175), (cx + 170, 175), 1)

    def _draw_disabled_labels(self) -> None:
        """Small 'AI features will be available in a later phase' note."""
        note_font = pygame.font.SysFont("segoeui", 12)
        for btn in [self.btn_aiai]:
            note = note_font.render(
                "AI opponents — Phase 2", True, DIM_TEXT_COLOR)
            nr = note.get_rect()
            nr.midtop = (btn.rect.centerx, btn.rect.bottom + 2)
            self.surface.blit(note, nr)

    def _draw_footer(self) -> None:
        footer = self.font_footer.render(
            "Assignment 1  •  Adversarial Search  •  IArt 2025/26", True, DIM_TEXT_COLOR)
        self.surface.blit(footer, footer.get_rect(
            center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT - 18)))


# ─── Player Name Screen ───────────────────────────────────────────────────────

class PlayerNameScreen:
    """
    Collect the names for Player 1 and Player 2 before starting a game.

    Callbacks:
      on_start(name1: str, name2: str)
      on_back()
    """

    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface

        pygame.font.init()
        self.font_title  = pygame.font.SysFont("segoeui", 36, bold=True)
        self.font_label  = pygame.font.SysFont("segoeui", 20, bold=True)
        self.font_input  = pygame.font.SysFont("segoeui", 22)
        self.font_hint   = pygame.font.SysFont("segoeui", 14)

        self.names = ["Player 1", "Player 2"]
        self._active_field = 0   # 0 or 1

        bw, bh = 200, 48
        cx = WINDOW_WIDTH // 2
        self.btn_start = _Button(
            pygame.Rect(cx - bw // 2, 430, bw, bh), "Start Game")
        self.btn_back  = _Button(
            pygame.Rect(cx - bw // 2, 495, bw, bh), "← Back",
            color=(50, 50, 80), hover_color=(70, 70, 110))

        self.on_start: Optional[Callable[[str, str], None]] = None
        self.on_back:  Optional[Callable] = None

        # Input box rects
        self._box_w = 360
        self._boxes = [
            pygame.Rect(cx - self._box_w // 2, 250, self._box_w, 46),
            pygame.Rect(cx - self._box_w // 2, 340, self._box_w, 46),
        ]

        self.on_human_vs_ai: Optional[Callable] = None

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, box in enumerate(self._boxes):
                if box.collidepoint(event.pos):
                    self._active_field = i

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_TAB:
                self._active_field = 1 - self._active_field
            elif event.key == pygame.K_RETURN:
                self._submit()
            elif event.key == pygame.K_ESCAPE:
                if self.on_back:
                    self.on_back()
            elif event.key == pygame.K_BACKSPACE:
                self.names[self._active_field] = self.names[self._active_field][:-1]
            else:
                char = event.unicode
                if char and len(self.names[self._active_field]) < 20:
                    self.names[self._active_field] += char

        if self.btn_start.handle_event(event):
            self._submit()
        if self.btn_back.handle_event(event) and self.on_back:
            self.on_back()

    def _submit(self) -> None:
        n1 = self.names[0].strip() or "Player 1"
        n2 = self.names[1].strip() or "Player 2"
        if self.on_start:
            self.on_start(n1, n2)

    def update(self) -> None:
        self.surface.fill(BG_COLOR)

        # Panel
        panel = pygame.Rect(WINDOW_WIDTH // 2 - 250, 80, 500, 480)
        pygame.draw.rect(self.surface, PANEL_COLOR, panel, border_radius=12)
        pygame.draw.rect(self.surface, BORDER_COLOR, panel, 2, border_radius=12)

        # Title
        title = self.font_title.render("Player Names", True, ACCENT_COLOR)
        self.surface.blit(title, title.get_rect(
            center=(WINDOW_WIDTH // 2, 130)))

        # Input fields
        labels  = ["Player 1 (Red)", "Player 2 (Blue)"]
        colors  = [P1_COLOR, P2_COLOR]
        for i, (box, label, col) in enumerate(zip(self._boxes, labels, colors)):
            # Label
            lbl = self.font_label.render(label, True, col)
            self.surface.blit(lbl, (box.x, box.y - 24))

            # Box background
            active = (i == self._active_field)
            box_col = (40, 50, 80) if active else (28, 30, 52)
            border_col = col if active else BORDER_COLOR
            pygame.draw.rect(self.surface, box_col, box, border_radius=6)
            pygame.draw.rect(self.surface, border_col, box, 2, border_radius=6)

            # Text
            display = self.names[i]
            if active:
                display += "|"   # cursor
            txt = self.font_input.render(display, True, WHITE)
            self.surface.blit(txt, (box.x + 10, box.y + 10))

        # Hint
        hint = self.font_hint.render(
            "TAB to switch fields  •  ENTER to start", True, DIM_TEXT_COLOR)
        self.surface.blit(hint, hint.get_rect(
            center=(WINDOW_WIDTH // 2, 400)))

        self.btn_start.draw(self.surface)
        self.btn_back.draw(self.surface)


# ─── AI Skill Screen ─────────────────────────────────────────────────────────

class AISkillScreen:
    """
    Choose the AI difficulty before starting Human vs AI.

    Callbacks:
      on_select(skill: str)
      on_back()
    """

    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface

        pygame.font.init()
        self.font_title = pygame.font.SysFont("segoeui", 36, bold=True)
        self.font_sub   = pygame.font.SysFont("segoeui", 17)

        bw, bh = 260, 52
        cx = WINDOW_WIDTH // 2 - bw // 2

        self.btn_easy = _Button(
            pygame.Rect(cx, 240, bw, bh),
            "Easy (defensive)",
            color=(80, 100, 140),
            hover_color=(95, 120, 170),
        )
        self.btn_medium = _Button(
            pygame.Rect(cx, 306, bw, bh),
            "Medium (balanced)",
            color=(70, 120, 90),
            hover_color=(90, 150, 110),
        )
        self.btn_hard = _Button(
            pygame.Rect(cx, 372, bw, bh),
            "Hard (aggressive)",
            color=(130, 90, 70),
            hover_color=(165, 115, 90),
        )
        self.btn_back = _Button(
            pygame.Rect(cx, 452, bw, 48),
            "← Back",
            color=(50, 50, 80),
            hover_color=(70, 70, 110),
        )

        self._buttons = [self.btn_easy, self.btn_medium, self.btn_hard, self.btn_back]

        self.on_select: Optional[Callable[[str], None]] = None
        self.on_back: Optional[Callable] = None

    def handle_event(self, event: pygame.event.Event) -> None:
        for btn in self._buttons:
            btn.update_hover(event)

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self.on_back:
                self.on_back()
            return

        if self.btn_easy.handle_event(event) and self.on_select:
            self.on_select("easy")
        if self.btn_medium.handle_event(event) and self.on_select:
            self.on_select("medium")
        if self.btn_hard.handle_event(event) and self.on_select:
            self.on_select("hard")
        if self.btn_back.handle_event(event) and self.on_back:
            self.on_back()

    def update(self) -> None:
        self.surface.fill(BG_COLOR)

        panel = pygame.Rect(WINDOW_WIDTH // 2 - 220, 120, 440, 420)
        pygame.draw.rect(self.surface, PANEL_COLOR, panel, border_radius=12)
        pygame.draw.rect(self.surface, BORDER_COLOR, panel, 2, border_radius=12)

        title = self.font_title.render("Choose AI Difficulty", True, ACCENT_COLOR)
        self.surface.blit(title, title.get_rect(center=(WINDOW_WIDTH // 2, 172)))

        subtitle = self.font_sub.render(
            "Select a level before starting Human vs AI", True, DIM_TEXT_COLOR
        )
        self.surface.blit(subtitle, subtitle.get_rect(center=(WINDOW_WIDTH // 2, 206)))

        for btn in self._buttons:
            btn.draw(self.surface)


# ─── Save / Load dialog ───────────────────────────────────────────────────────

class SaveDialog:
    """
    Simple save-game dialog: shows a text field for the filename and
    confirms or cancels.

    on_save(filepath: str) is called with the chosen absolute path.
    on_cancel() is called on cancellation.
    """

    _SAVE_DIR = os.path.join(os.path.dirname(__file__), "..", "saves")

    def __init__(self, surface: pygame.Surface,
                 on_save: Callable[[str], None],
                 on_cancel: Callable) -> None:
        self.surface   = surface
        self.on_save   = on_save
        self.on_cancel = on_cancel

        pygame.font.init()
        self.font_title = pygame.font.SysFont("segoeui", 28, bold=True)
        self.font_body  = pygame.font.SysFont("segoeui", 18)
        self.font_hint  = pygame.font.SysFont("segoeui", 13)

        self.filename = "game_save"
        self._box = pygame.Rect(WINDOW_WIDTH // 2 - 180, 300, 360, 46)

        bw, bh = 160, 44
        cx = WINDOW_WIDTH // 2
        self.btn_save   = _Button(pygame.Rect(cx - bw - 10, 380, bw, bh), "Save")
        self.btn_cancel = _Button(pygame.Rect(cx + 10,      380, bw, bh), "Cancel",
                                  color=(60, 50, 50),
                                  hover_color=(90, 70, 70))

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.on_cancel()
            elif event.key == pygame.K_RETURN:
                self._do_save()
            elif event.key == pygame.K_BACKSPACE:
                self.filename = self.filename[:-1]
            else:
                char = event.unicode
                # Allow only safe filename characters
                if char and char not in r'\/:*?"<>|' and len(self.filename) < 40:
                    self.filename += char

        if self.btn_save.handle_event(event):
            self._do_save()
        if self.btn_cancel.handle_event(event):
            self.on_cancel()

    def _do_save(self) -> None:
        os.makedirs(self._SAVE_DIR, exist_ok=True)
        fname = (self.filename.strip() or "game_save") + ".txt"
        path  = os.path.join(self._SAVE_DIR, fname)
        self.on_save(path)

    def update(self) -> None:
        # Dim overlay
        overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.surface.blit(overlay, (0, 0))

        # Panel
        panel = pygame.Rect(WINDOW_WIDTH // 2 - 220, 220, 440, 250)
        pygame.draw.rect(self.surface, PANEL_COLOR, panel, border_radius=12)
        pygame.draw.rect(self.surface, BORDER_COLOR, panel, 2, border_radius=12)

        title = self.font_title.render("Save Game", True, ACCENT_COLOR)
        self.surface.blit(title, title.get_rect(
            center=(WINDOW_WIDTH // 2, 260)))

        lbl = self.font_body.render("Filename:", True, TEXT_COLOR)
        self.surface.blit(lbl, (self._box.x, self._box.y - 26))

        # Input box
        pygame.draw.rect(self.surface, (40, 50, 80), self._box, border_radius=6)
        pygame.draw.rect(self.surface, ACCENT_COLOR, self._box, 2, border_radius=6)
        inp = self.font_body.render(self.filename + "|", True, WHITE)
        self.surface.blit(inp, (self._box.x + 10, self._box.y + 10))

        hint = self.font_hint.render(
            f"Saves to: saves/{self.filename or 'game_save'}.txt", True, DIM_TEXT_COLOR)
        self.surface.blit(hint, hint.get_rect(
            center=(WINDOW_WIDTH // 2, 355)))

        self.btn_save.draw(self.surface)
        self.btn_cancel.draw(self.surface)


class LoadDialog:
    """
    Simple load-game dialog: lists .txt files in the saves/ directory.

    on_load(filepath: str) is called with the chosen absolute path.
    on_cancel() is called on cancellation.
    """

    _SAVE_DIR = os.path.join(os.path.dirname(__file__), "..", "saves")

    def __init__(self, surface: pygame.Surface,
                 on_load: Callable[[str], None],
                 on_cancel: Callable) -> None:
        self.surface   = surface
        self.on_load   = on_load
        self.on_cancel = on_cancel

        pygame.font.init()
        self.font_title = pygame.font.SysFont("segoeui", 28, bold=True)
        self.font_item  = pygame.font.SysFont("segoeui", 17)
        self.font_hint  = pygame.font.SysFont("segoeui", 13)
        self.font_empty = pygame.font.SysFont("segoeui", 16)

        self._files: List[str] = []
        self._selected_idx: int = -1
        self._scroll: int = 0
        self._VISIBLE = 6
        self._ITEM_H  = 38

        self._refresh_files()

        bw, bh = 160, 44
        cx = WINDOW_WIDTH // 2
        self.btn_load   = _Button(pygame.Rect(cx - bw - 10, 520, bw, bh), "Load",
                                  enabled=False)
        self.btn_cancel = _Button(pygame.Rect(cx + 10, 520, bw, bh), "Cancel",
                                  color=(60, 50, 50), hover_color=(90, 70, 70))

        self._list_rect = pygame.Rect(WINDOW_WIDTH // 2 - 200, 290,
                                      400, self._VISIBLE * self._ITEM_H)

    def _refresh_files(self) -> None:
        os.makedirs(self._SAVE_DIR, exist_ok=True)
        self._files = sorted(
            f for f in os.listdir(self._SAVE_DIR) if f.endswith(".txt")
        )

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.on_cancel()
            elif event.key == pygame.K_RETURN and self._selected_idx >= 0:
                self._do_load()
            elif event.key == pygame.K_DOWN:
                self._selected_idx = min(self._selected_idx + 1, len(self._files) - 1)
                self._ensure_visible()
            elif event.key == pygame.K_UP:
                self._selected_idx = max(self._selected_idx - 1, 0)
                self._ensure_visible()

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._list_rect.collidepoint(event.pos):
                rel_y = event.pos[1] - self._list_rect.y
                idx   = self._scroll + rel_y // self._ITEM_H
                if 0 <= idx < len(self._files):
                    self._selected_idx = idx
                    self.btn_load.enabled = True

        if event.type == pygame.MOUSEWHEEL:
            self._scroll = max(0,
                min(self._scroll - event.y, max(0, len(self._files) - self._VISIBLE)))

        if self.btn_load.handle_event(event):
            self._do_load()
        if self.btn_cancel.handle_event(event):
            self.on_cancel()

    def _ensure_visible(self) -> None:
        if self._selected_idx < self._scroll:
            self._scroll = self._selected_idx
        elif self._selected_idx >= self._scroll + self._VISIBLE:
            self._scroll = self._selected_idx - self._VISIBLE + 1
        self.btn_load.enabled = (self._selected_idx >= 0)

    def _do_load(self) -> None:
        if 0 <= self._selected_idx < len(self._files):
            path = os.path.join(self._SAVE_DIR, self._files[self._selected_idx])
            self.on_load(path)

    def update(self) -> None:
        overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.surface.blit(overlay, (0, 0))

        panel = pygame.Rect(WINDOW_WIDTH // 2 - 230, 200, 460, 390)
        pygame.draw.rect(self.surface, PANEL_COLOR, panel, border_radius=12)
        pygame.draw.rect(self.surface, BORDER_COLOR, panel, 2, border_radius=12)

        title = self.font_title.render("Load Game", True, ACCENT_COLOR)
        self.surface.blit(title, title.get_rect(
            center=(WINDOW_WIDTH // 2, 240)))

        # File list
        pygame.draw.rect(self.surface, (20, 22, 40), self._list_rect, border_radius=6)
        pygame.draw.rect(self.surface, BORDER_COLOR, self._list_rect, 1, border_radius=6)

        if not self._files:
            empty_txt = self.font_empty.render("No save files found.", True, DIM_TEXT_COLOR)
            self.surface.blit(empty_txt, empty_txt.get_rect(
                center=self._list_rect.center))
        else:
            for i in range(self._VISIBLE):
                idx = self._scroll + i
                if idx >= len(self._files):
                    break
                item_rect = pygame.Rect(
                    self._list_rect.x, self._list_rect.y + i * self._ITEM_H,
                    self._list_rect.w, self._ITEM_H,
                )
                if idx == self._selected_idx:
                    pygame.draw.rect(self.surface, (40, 80, 140), item_rect, border_radius=4)
                lbl = self.font_item.render(self._files[idx], True, TEXT_COLOR)
                self.surface.blit(lbl, (item_rect.x + 12, item_rect.y + 8))

        hint = self.font_hint.render(
            "Click to select  •  ↑↓ keys to navigate  •  ENTER to load", True, DIM_TEXT_COLOR)
        self.surface.blit(hint, hint.get_rect(
            center=(WINDOW_WIDTH // 2, 505)))

        self.btn_load.draw(self.surface)
        self.btn_cancel.draw(self.surface)
