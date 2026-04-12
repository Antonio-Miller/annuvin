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
import threading
import sys
import time
from datetime import datetime
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
from annuvin.game import AnnuvinGame, AILogger
from annuvin.renderer import BoardRenderer
from annuvin.menu import (
    MainMenu,
    PlayerNameScreen,
    AISkillScreen,
    AIVsAISkillScreen,
    SaveDialog,
    LoadDialog,
)
from annuvin.rules_screen import RulesScreen


# ─── Application states ───────────────────────────────────────────────────────

class AppState(Enum):
    MAIN_MENU    = auto()
    PLAYER_NAMES = auto()
    AI_SKILL     = auto()
    AI_VS_AI_SKILL = auto()
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
        self._ai_players: dict = {}
        self._ai_think_start: float = 0.0
        self._ai_think_delay: float = 0.8
        self._ai_thinking = False
        self._ai_pending_move = None
        self._ai_logger: Optional[AILogger] = None
        self._human_logger: Optional[AILogger] = None

        # Game state
        self._state: AppState       = AppState.MAIN_MENU
        self._game: Optional[AnnuvinGame]        = None
        self._renderer: Optional[BoardRenderer]  = None
        self._player_names          = {1: "Player 1", 2: "Player 2"}
        self._mode: str             = GameMode.HUMAN_VS_HUMAN

        # ── Stats tracking ───────────────────────────────────────────────────
        self._stats = {
            1: {"moves": 0, "captures": 0, "total_time": 0.0, "move_times": []},
            2: {"moves": 0, "captures": 0, "total_time": 0.0, "move_times": []},
        }
        self._game_start_time: float = 0.0
        self._turn_start_time: float = 0.0
        self._stats_exported: bool = False

        # ── AI vs AI watchability ────────────────────────────────────────────
        self._aivsai_paused: bool = False
        self._aivsai_delay: float = 1.0       # seconds between moves
        self._aivsai_next_time: float = 0.0   # when to trigger next move
        self._aivsai_step_once: bool = False   # step-through mode
        self._aivsai_speed_idx: int = 1        # 0=fast, 1=normal, 2=slow
        self._SPEED_OPTIONS = [0.3, 1.0, 2.0]
        self._SPEED_LABELS = ["Fast", "Normal", "Slow"]

        # ── Hint system ──────────────────────────────────────────────────────
        self._hint_thinking: bool = False
        self._hint_move = None

        # Fonts (shared)
        self._font_medium = pygame.font.SysFont("segoeui", 18)
        self._font_small  = pygame.font.SysFont("segoeui", 14)

        # Screen objects are created lazily / on demand
        self._main_menu: Optional[MainMenu]              = None
        self._player_name_screen: Optional[PlayerNameScreen] = None
        self._ai_skill_screen: Optional[AISkillScreen]   = None
        self._aivsai_skill_screen: Optional[AIVsAISkillScreen] = None
        self._rules_screen: Optional[RulesScreen]        = None
        self._save_dialog: Optional[SaveDialog]          = None
        self._load_dialog: Optional[LoadDialog]          = None

        self._init_main_menu()

    # ── Screen factories ──────────────────────────────────────────────────────

    def _init_main_menu(self) -> None:
        m = MainMenu(self.screen)
        m.on_human_vs_human = self._go_to_player_names
        m.on_human_vs_ai    = self._go_to_ai_skill_select
        m.on_ai_vs_ai       = self._go_to_aivsai_skill_select
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
        self._ai_pending_move = None
        self._ai_thinking = False
        self._hint_thinking = False
        self._hint_move = None
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

    def _reset_stats(self) -> None:
        self._stats = {
            1: {"moves": 0, "captures": 0, "total_time": 0.0, "move_times": []},
            2: {"moves": 0, "captures": 0, "total_time": 0.0, "move_times": []},
        }
        self._game_start_time = time.time()
        self._turn_start_time = time.time()
        self._stats_exported = False

    def _start_hvh_game(self, name1: str, name2: str) -> None:
        self._player_names = {1: name1, 2: name2}
        self._mode = GameMode.HUMAN_VS_HUMAN
        self._ai = None
        self._ai_players = {}
        self._game = AnnuvinGame()
        self._reset_stats()
        self._setup_renderer()
        self._state = AppState.PLAYING

    def _setup_renderer(self) -> None:
        r = BoardRenderer(self.screen, self._game)
        r.player_names      = self._player_names
        r.on_move_selected  = self._apply_human_move
        r.on_save_requested = self._go_to_save_dialog
        r.on_quit_requested = self._go_to_main_menu

        # Human control policy by mode
        if self._mode == GameMode.HUMAN_VS_AI:
            r.human_players = {1}
        elif self._mode == GameMode.AI_VS_AI:
            r.human_players = set()
        else:
            r.human_players = {1, 2}   # both human in HvH

        # AI vs AI controls
        r.is_aivsai = (self._mode == GameMode.AI_VS_AI)
        r.aivsai_paused = self._aivsai_paused
        r.aivsai_speed_label = self._SPEED_LABELS[self._aivsai_speed_idx]
        r.on_pause_toggle = self._toggle_pause
        r.on_speed_change = self._cycle_speed
        r.on_step_once = self._step_once

        # Hint callback
        r.is_human_mode = (self._mode in (GameMode.HUMAN_VS_HUMAN, GameMode.HUMAN_VS_AI))
        r.on_hint_requested = self._request_hint
        r.hint_move = None

        # Stats reference
        r.game_stats = self._stats

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
        skill_screen = AISkillScreen(self.screen)
        skill_screen.on_select = lambda skill: self._start_hvai_game("Player 1", skill)
        skill_screen.on_back = self._go_to_main_menu
        self._ai_skill_screen = skill_screen
        self._state = AppState.AI_SKILL

    def _go_to_aivsai_skill_select(self) -> None:
        skill_screen = AIVsAISkillScreen(self.screen)
        skill_screen.on_start = self._start_aivsai_game
        skill_screen.on_back = self._go_to_main_menu
        self._aivsai_skill_screen = skill_screen
        self._state = AppState.AI_VS_AI_SKILL

    def _start_hvai_game(self, name1: str, skill: str) -> None:
        from annuvin.game import MinimaxAI
        self._player_names = {1: name1, 2: f"AI ({skill})"}
        self._mode = GameMode.HUMAN_VS_AI
        self._ai_players = {}
        self._game = AnnuvinGame()
        self._reset_stats()
        log_path = os.path.join(_HERE, "logs", "ai_thinking.log")
        human_log_path = os.path.join(_HERE, "logs", "human_choices.log")
        self._ai_logger = AILogger(log_path, clear=True)
        self._human_logger = AILogger(human_log_path, clear=True)
        self._ai_logger.log(
            f"New AI session started: mode={self._mode}, skill={skill}, "
            f"player1={name1}, player2=AI"
        )
        self._ai_logger.log(f"Initial board state:\n{self._game.to_text().rstrip()}")
        self._human_logger.log(
            f"New human-choice session started: mode={self._mode}, skill={skill}, "
            f"player1={name1}, player2=AI"
        )
        self._human_logger.log(f"Initial board state:\n{self._game.to_text().rstrip()}")
        self._ai = MinimaxAI(player=2, skill=skill, logger=self._ai_logger)
        self._setup_renderer()
        self._state = AppState.PLAYING

    def _start_aivsai_game(self, p1_skill: str, p2_skill: str) -> None:
        from annuvin.game import MinimaxAI
        self._player_names = {1: f"AI 1 ({p1_skill})", 2: f"AI 2 ({p2_skill})"}
        self._mode = GameMode.AI_VS_AI
        self._ai = None
        self._game = AnnuvinGame()
        self._reset_stats()

        # Reset AI vs AI controls
        self._aivsai_paused = False
        self._aivsai_step_once = False

        log_path = os.path.join(_HERE, "logs", "ai_thinking.log")
        self._ai_logger = AILogger(log_path, clear=True)
        self._human_logger = None
        self._ai_logger.log(
            f"New AI vs AI session started: p1_skill={p1_skill}, p2_skill={p2_skill}"
        )
        self._ai_logger.log(f"Initial board state:\n{self._game.to_text().rstrip()}")

        self._ai_players = {
            1: MinimaxAI(player=1, skill=p1_skill, logger=self._ai_logger),
            2: MinimaxAI(player=2, skill=p2_skill, logger=self._ai_logger),
        }

        self._setup_renderer()
        self._state = AppState.PLAYING
        self._do_ai_move()

    # ── AI vs AI controls ────────────────────────────────────────────────────

    def _toggle_pause(self) -> None:
        self._aivsai_paused = not self._aivsai_paused
        if self._renderer:
            self._renderer.aivsai_paused = self._aivsai_paused

    def _cycle_speed(self) -> None:
        self._aivsai_speed_idx = (self._aivsai_speed_idx + 1) % len(self._SPEED_OPTIONS)
        self._aivsai_delay = self._SPEED_OPTIONS[self._aivsai_speed_idx]
        if self._renderer:
            self._renderer.aivsai_speed_label = self._SPEED_LABELS[self._aivsai_speed_idx]

    def _step_once(self) -> None:
        self._aivsai_step_once = True
        if not self._ai_thinking and self._ai_pending_move is None:
            self._do_ai_move()

    # ── Hint system ──────────────────────────────────────────────────────────

    def _request_hint(self) -> None:
        if self._hint_thinking or self._ai_thinking:
            return
        if not self._game or self._game.game_over:
            return
        self._hint_thinking = True
        self._hint_move = None
        if self._renderer:
            self._renderer.hint_move = None
        game_snapshot = self._game.clone()
        player = game_snapshot.current_player

        def run():
            from annuvin.game import MinimaxAI
            hint_ai = MinimaxAI(player=player, skill="medium")
            move = hint_ai.choose_move(game_snapshot)
            self._hint_move = move
            self._hint_thinking = False

        threading.Thread(target=run, daemon=True).start()

    # ── Game actions ──────────────────────────────────────────────────────────

    def _record_move_stats(self, player: int, move, move_time: float) -> None:
        self._stats[player]["moves"] += 1
        self._stats[player]["captures"] += len(move.captures)
        self._stats[player]["total_time"] += move_time
        self._stats[player]["move_times"].append(move_time)

    def _apply_human_move(self, move) -> None:
        if self._game and not self._game.game_over:
            move_time = time.time() - self._turn_start_time
            player = self._game.current_player
            if self._human_logger is not None:
                self._human_logger.log(
                    f"Human player {player} chose move: "
                    f"{move.origin} -> {move.destination}, caps={len(move.captures)}, "
                    f"path={move.path}"
                )
            self._game.apply_move(move)
            self._record_move_stats(player, move, move_time)
            # Clear hint after move
            self._hint_move = None
            if self._renderer:
                self._renderer.hint_move = None
            if self._human_logger is not None:
                self._human_logger.log(
                    f"Board after human move:\n{self._game.to_text().rstrip()}"
                )
            self._turn_start_time = time.time()
            # Export stats on game over
            if self._game.game_over:
                self._export_game_results()
            # If it's now the AI's turn, trigger it
            if (self._mode == GameMode.HUMAN_VS_AI
                    and self._ai
                    and not self._game.game_over
                    and self._game.current_player == 2):
                self._do_ai_move()

    def _do_ai_move(self) -> None:
        self._ai_thinking = True
        self._ai_think_start = time.time()
        self._turn_start_time = time.time()
        game_snapshot = self._game.clone()

        if self._mode == GameMode.AI_VS_AI:
            ai_player = self._ai_players.get(game_snapshot.current_player)
        else:
            ai_player = self._ai

        if ai_player is None:
            self._ai_thinking = False
            return

        def run():
            move = ai_player.choose_move(game_snapshot)
            self._ai_pending_move = move
            self._ai_thinking = False

        self._ai_pending_move = None
        threading.Thread(target=run, daemon=True).start()

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
            self._ai = None
            self._ai_players = {}
            self._ai_pending_move = None
            self._ai_thinking = False
            self._reset_stats()
            self._setup_renderer()
            self._state = AppState.PLAYING
            self._show_toast(f"Loaded {os.path.basename(filepath)}", success=True)
        except (OSError, ValueError) as exc:
            self._show_toast(f"Load failed: {exc}", success=False)
            self._go_to_main_menu()

    # ── Game results export ──────────────────────────────────────────────────

    def _export_game_results(self) -> None:
        if self._stats_exported:
            return
        self._stats_exported = True
        results_dir = os.path.join(_HERE, "results")
        os.makedirs(results_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(results_dir, f"game_{timestamp}.txt")
        total_time = time.time() - self._game_start_time

        lines = []
        lines.append("=" * 60)
        lines.append("ANNUVIN — Game Results")
        lines.append("=" * 60)
        lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Mode: {self._mode}")
        lines.append(f"Player 1: {self._player_names[1]}")
        lines.append(f"Player 2: {self._player_names[2]}")
        lines.append("")

        # Result
        if self._game.winner == 0:
            lines.append("Result: Draw (move limit reached)")
        elif self._game.winner:
            lines.append(f"Result: {self._player_names[self._game.winner]} wins!")
        lines.append(f"Total moves: {self._game.move_count}")
        lines.append(f"Total game time: {total_time:.1f}s")
        lines.append("")

        # Per-player stats
        lines.append("-" * 40)
        for p in [1, 2]:
            s = self._stats[p]
            avg_time = s["total_time"] / s["moves"] if s["moves"] > 0 else 0.0
            lines.append(f"{self._player_names[p]}:")
            lines.append(f"  Moves: {s['moves']}")
            lines.append(f"  Captures: {s['captures']}")
            lines.append(f"  Total thinking time: {s['total_time']:.2f}s")
            lines.append(f"  Avg time per move: {avg_time:.3f}s")
            lines.append(f"  Pieces remaining: {self._game.piece_count(p)}")
            lines.append("")
        lines.append("-" * 40)

        # Move history
        lines.append("")
        lines.append(self._game.history_to_text())

        try:
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
        except OSError:
            pass

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

            # ── Process pending AI move ──────────────────────────────────────
            if (self._mode in (GameMode.HUMAN_VS_AI, GameMode.AI_VS_AI)
                    and self._ai_pending_move is not None
                    and not self._ai_thinking):

                if self._mode == GameMode.AI_VS_AI:
                    # Apply with delay for watchability
                    if time.time() >= self._aivsai_next_time:
                        move = self._ai_pending_move
                        self._ai_pending_move = None
                        if self._game and not self._game.game_over:
                            move_time = time.time() - self._turn_start_time
                            player = self._game.current_player
                            self._game.apply_move(move)
                            self._record_move_stats(player, move, move_time)
                            if self._game.game_over:
                                self._export_game_results()
                            elif not self._aivsai_paused or self._aivsai_step_once:
                                self._aivsai_step_once = False
                                self._aivsai_next_time = time.time() + self._aivsai_delay
                                self._do_ai_move()
                else:
                    # Human vs AI — apply immediately
                    move = self._ai_pending_move
                    self._ai_pending_move = None
                    if self._game and not self._game.game_over:
                        move_time = time.time() - self._turn_start_time
                        player = self._game.current_player
                        self._game.apply_move(move)
                        self._record_move_stats(player, move, move_time)
                        self._turn_start_time = time.time()
                        if self._game.game_over:
                            self._export_game_results()

            # ── AI vs AI: resume from pause when step requested ──────────────
            if (self._mode == GameMode.AI_VS_AI
                    and self._aivsai_paused
                    and self._aivsai_step_once
                    and not self._ai_thinking
                    and self._ai_pending_move is None
                    and self._game and not self._game.game_over):
                self._aivsai_step_once = False
                self._aivsai_next_time = 0
                self._do_ai_move()

            # ── AI vs AI: resume from unpause ────────────────────────────────
            if (self._mode == GameMode.AI_VS_AI
                    and not self._aivsai_paused
                    and not self._ai_thinking
                    and self._ai_pending_move is None
                    and self._game and not self._game.game_over
                    and self._state == AppState.PLAYING):
                if time.time() >= self._aivsai_next_time:
                    self._do_ai_move()

            # ── Process pending hint ─────────────────────────────────────────
            if self._hint_move is not None and not self._hint_thinking:
                if self._renderer:
                    self._renderer.hint_move = self._hint_move
                self._hint_move = None

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
        elif self._state == AppState.AI_SKILL and self._ai_skill_screen:
            self._ai_skill_screen.handle_event(event)
        elif self._state == AppState.AI_VS_AI_SKILL and self._aivsai_skill_screen:
            self._aivsai_skill_screen.handle_event(event)
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
        elif self._state == AppState.AI_SKILL and self._ai_skill_screen:
            self._ai_skill_screen.update()
        elif self._state == AppState.AI_VS_AI_SKILL and self._aivsai_skill_screen:
            self._aivsai_skill_screen.update()
        elif self._state == AppState.RULES and self._rules_screen:
            self._rules_screen.update()
        elif self._state == AppState.PLAYING and self._renderer:
            self._renderer.ai_think_start = self._ai_think_start if self._ai_thinking else 0.0
            self._renderer.hint_thinking = self._hint_thinking
            self._renderer.update()
        elif self._state == AppState.SAVE_DIALOG:
            # Draw game underneath
            if self._renderer:
                self._renderer.ai_think_start = self._ai_think_start if self._ai_thinking else 0.0
                self._renderer.update()
            if self._save_dialog:
                self._save_dialog.update()
        elif self._state == AppState.LOAD_DIALOG:
            if self._main_menu:
                self._main_menu.update()
            if self._load_dialog:
                self._load_dialog.update()

# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = AnnuvinApp()
    app.run()
