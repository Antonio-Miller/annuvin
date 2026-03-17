"""
main.py — Entry point for Annuvin.

Application state machine:
  MAIN_MENU   → (Human vs Human) → PLAYER_NAMES → PLAYING
  MAIN_MENU   → (Rules)          → RULES
  MAIN_MENU   → (Load Game)      → LOAD_DIALOG  → PLAYING
  PLAYING     → (Quit to Menu)   → MAIN_MENU
  PLAYING     → (Save)           → SAVE_DIALOG  → PLAYING
  RULES       → (Back)           → MAIN_MENU
  Game Over   → (ENTER)          → MAIN_MENU

Controls during a game:
  Mouse left-click — select / move pieces
  ESC             — open quit confirmation / return to menu
  ENTER           — confirm game-over screen
"""

from __future__ import annotations

import os
import sys
import time
from enum import Enum, auto
from typing import Optional

import pygame

# Ensure the project root is in the Python path so the package can be found
# regardless of where `python main.py` is invoked from.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from annuvin.constants import (
    WINDOW_WIDTH, WINDOW_HEIGHT, FPS, TITLE,
    BG_COLOR, PANEL_COLOR, BORDER_COLOR,
    TEXT_COLOR, DIM_TEXT_COLOR, ACCENT_COLOR, WHITE,
    BUTTON_COLOR, BUTTON_HOVER_COLOR,
    P1_COLOR, P2_COLOR,
    GameMode,
)
from annuvin.board import HexBoard
from annuvin.game import AnnuvinGame
from annuvin.renderer import BoardRenderer
from annuvin.menu import MainMenu, PlayerNameScreen, SaveDialog, LoadDialog
from annuvin.rules_screen import RulesScreen


# ─── Application states ───────────────────────────────────────────────────────

class AppState(Enum):
    MAIN_MENU    = auto()
    PLAYER_NAMES = auto()
    PLAYING      = auto()
    RULES        = auto()
    SAVE_DIALOG  = auto()
    LOAD_DIALOG  = auto()
    QUIT_CONFIRM = auto()


# ─── Application ─────────────────────────────────────────────────────────────

class AnnuvinApp:
    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption(TITLE)
        self.screen  = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        self.clock   = pygame.time.Clock()
        self.running = True
        self._ai: Optional[object] = None  

        # Game state
        self._state: AppState       = AppState.MAIN_MENU
        self._game: Optional[AnnuvinGame]        = None
        self._renderer: Optional[BoardRenderer]  = None
        self._player_names          = {1: "Player 1", 2: "Player 2"}
        self._mode: str             = GameMode.HUMAN_VS_HUMAN

        # Fonts (shared)
        self._font_medium = pygame.font.SysFont("segoeui", 18)
        self._font_small  = pygame.font.SysFont("segoeui", 14)

        # Screen objects are created lazily / on demand
        self._main_menu: Optional[MainMenu]              = None
        self._player_name_screen: Optional[PlayerNameScreen] = None
        self._rules_screen: Optional[RulesScreen]        = None
        self._save_dialog: Optional[SaveDialog]          = None
        self._load_dialog: Optional[LoadDialog]          = None

        self._init_main_menu()

    # ── Screen factories ──────────────────────────────────────────────────────

    def _init_main_menu(self) -> None:
        m = MainMenu(self.screen)
        m.on_human_vs_human = self._go_to_player_names
        m.on_human_vs_ai    = self._go_to_ai_skill_select
        m.on_rules          = self._go_to_rules
        m.on_load_game      = self._go_to_load_dialog
        m.on_quit           = self._quit
        self._main_menu = m

    def _go_to_player_names(self) -> None:
        ps = PlayerNameScreen(self.screen)
        ps.on_start = self._start_hvh_game
        ps.on_back  = self._go_to_main_menu
        self._player_name_screen = ps
        self._state = AppState.PLAYER_NAMES

    def _go_to_main_menu(self) -> None:
        self._state = AppState.MAIN_MENU

    def _go_to_rules(self) -> None:
        self._rules_screen = RulesScreen(self.screen, on_back=self._go_to_main_menu)
        self._state = AppState.RULES

    def _go_to_load_dialog(self) -> None:
        self._load_dialog = LoadDialog(
            self.screen,
            on_load=self._load_game_from_file,
            on_cancel=self._go_to_main_menu,
        )
        self._state = AppState.LOAD_DIALOG

    def _start_hvh_game(self, name1: str, name2: str) -> None:
        self._player_names = {1: name1, 2: name2}
        self._mode = GameMode.HUMAN_VS_HUMAN
        self._game = AnnuvinGame()
        self._setup_renderer()
        self._state = AppState.PLAYING

    def _setup_renderer(self) -> None:
        r = BoardRenderer(self.screen, self._game)
        r.on_move_selected  = self._apply_human_move
        r.on_save_requested = self._go_to_save_dialog
        r.on_quit_requested = self._go_to_main_menu
        self._renderer = r

    def _go_to_save_dialog(self) -> None:
        self._save_dialog = SaveDialog(
            self.screen,
            on_save=self._save_game_to_file,
            on_cancel=self._return_to_playing,
        )
        self._state = AppState.SAVE_DIALOG

    def _return_to_playing(self) -> None:
        self._state = AppState.PLAYING

    def _quit(self) -> None:
        self.running = False

    def _go_to_ai_skill_select(self) -> None:
        # For now, just launch with medium difficulty
        # You can add a proper skill screen later
        self._start_hvai_game("Player 1", "medium")

    def _start_hvai_game(self, name1: str, skill: str) -> None:
        from annuvin.game import MinimaxAI
        self._player_names = {1: name1, 2: f"AI ({skill})"}
        self._mode = GameMode.HUMAN_VS_AI
        self._game = AnnuvinGame()
        self._ai = MinimaxAI(player=2, skill=skill)
        self._setup_renderer()
        self._state = AppState.PLAYING

    # ── Game actions ──────────────────────────────────────────────────────────

    def _apply_human_move(self, move) -> None:
        if self._game and not self._game.game_over:
            self._game.apply_move(move)
            # If it's now the AI's turn, trigger it
            if (self._mode == GameMode.HUMAN_VS_AI
                    and self._ai
                    and not self._game.game_over
                    and self._game.current_player == 2):
                self._do_ai_move()

    def _do_ai_move(self) -> None:
        if self._game and self._ai:
            move = self._ai.choose_move(self._game)
            if move:
                self._game.apply_move(move)
    # ── Save / Load ───────────────────────────────────────────────────────────

    def _save_game_to_file(self, filepath: str) -> None:
        """Serialise the current game state and write to *filepath*."""
        if self._game is None:
            self._return_to_playing()
            return
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        content  = self._game.to_text()
        content += "\n--- HISTORY ---\n"
        content += self._game.history_to_text()
        content += f"\nNAMES {self._player_names[1]} | {self._player_names[2]}\n"
        try:
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(content)
            self._show_toast(f"Saved to {os.path.basename(filepath)}", success=True)
        except OSError as exc:
            self._show_toast(f"Save failed: {exc}", success=False)
        self._return_to_playing()

    def _load_game_from_file(self, filepath: str) -> None:
        """Load a game state from *filepath*."""
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                text = fh.read()
            # Only read up to the history separator
            board_text = text.split("--- HISTORY ---")[0]
            game = AnnuvinGame.from_text(board_text)

            # Try to recover player names
            for line in text.splitlines():
                if line.startswith("NAMES "):
                    parts = line[6:].split("|")
                    if len(parts) == 2:
                        self._player_names = {
                            1: parts[0].strip(),
                            2: parts[1].strip(),
                        }
            self._game = game
            self._mode = GameMode.HUMAN_VS_HUMAN
            self._setup_renderer()
            self._state = AppState.PLAYING
            self._show_toast(f"Loaded {os.path.basename(filepath)}", success=True)
        except (OSError, ValueError) as exc:
            self._show_toast(f"Load failed: {exc}", success=False)
            self._go_to_main_menu()

    # ── Toast notification ────────────────────────────────────────────────────

    _toast_text: str = ""
    _toast_until: float = 0.0
    _toast_success: bool = True

    def _show_toast(self, text: str, success: bool = True) -> None:
        self._toast_text    = text
        self._toast_until   = time.time() + 3.0
        self._toast_success = success

    def _draw_toast(self) -> None:
        if time.time() > self._toast_until:
            return
        col   = (40, 160, 80) if self._toast_success else (160, 50, 50)
        font  = self._font_medium
        surf  = font.render(self._toast_text, True, WHITE)
        pad   = 14
        rect  = pygame.Rect(
            WINDOW_WIDTH // 2 - surf.get_width() // 2 - pad,
            WINDOW_HEIGHT - 60,
            surf.get_width() + pad * 2, surf.get_height() + pad,
        )
        pygame.draw.rect(self.screen, col, rect, border_radius=8)
        self.screen.blit(surf, (rect.x + pad, rect.y + pad // 2))

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        while self.running:
            self.clock.tick(FPS)
            events = pygame.event.get()

            for event in events:
                if event.type == pygame.QUIT:
                    self.running = False

                # Global ESC handling
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if self._state == AppState.PLAYING:
                        self._go_to_main_menu()
                    elif self._state in (AppState.SAVE_DIALOG, AppState.LOAD_DIALOG):
                        if self._game:
                            self._return_to_playing()
                        else:
                            self._go_to_main_menu()

                # ENTER to dismiss game-over screen
                if event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                    if (self._state == AppState.PLAYING
                            and self._game and self._game.game_over):
                        self._go_to_main_menu()

                # Route events to the active screen
                self._dispatch_event(event)

            self._draw()
            self._draw_toast()
            pygame.display.flip()

        pygame.quit()
        sys.exit(0)

    def _dispatch_event(self, event: pygame.event.Event) -> None:
        if self._state == AppState.MAIN_MENU and self._main_menu:
            self._main_menu.handle_event(event)
        elif self._state == AppState.PLAYER_NAMES and self._player_name_screen:
            self._player_name_screen.handle_event(event)
        elif self._state == AppState.RULES and self._rules_screen:
            self._rules_screen.handle_event(event)
        elif self._state == AppState.PLAYING and self._renderer:
            self._renderer.handle_event(event)
        elif self._state == AppState.SAVE_DIALOG and self._save_dialog:
            self._save_dialog.handle_event(event)
        elif self._state == AppState.LOAD_DIALOG and self._load_dialog:
            self._load_dialog.handle_event(event)

    def _draw(self) -> None:
        if self._state == AppState.MAIN_MENU and self._main_menu:
            self._main_menu.update()
        elif self._state == AppState.PLAYER_NAMES and self._player_name_screen:
            self._player_name_screen.update()
        elif self._state == AppState.RULES and self._rules_screen:
            self._rules_screen.update()
        elif self._state == AppState.PLAYING and self._renderer:
            self._renderer.update()
            self._draw_player_name_labels()
        elif self._state == AppState.SAVE_DIALOG:
            # Draw game underneath
            if self._renderer:
                self._renderer.update()
            if self._save_dialog:
                self._save_dialog.update()
        elif self._state == AppState.LOAD_DIALOG:
            if self._main_menu:
                self._main_menu.update()
            if self._load_dialog:
                self._load_dialog.update()

    def _draw_player_name_labels(self) -> None:
        """Overlay player names on the sidebar."""
        if not self._renderer:
            return
        from annuvin.renderer import BoardRenderer
        sx = WINDOW_WIDTH - BoardRenderer.SIDEBAR_WIDTH + 20
        font = self._font_small
        n1 = self._font_small.render(
            f"  {self._player_names[1]}", True, P1_COLOR)
        n2 = self._font_small.render(
            f"  {self._player_names[2]}", True, P2_COLOR)
        y_base = 268   # just below the piece-count lines
        self.screen.blit(n1, (sx + 70, y_base))
        self.screen.blit(n2, (sx + 70, y_base + 28))


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = AnnuvinApp()
    app.run()
