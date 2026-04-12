"""
renderer.py — Pygame rendering of the Annuvin board and game state.

MULTI-STEP TURN MODEL
─────────────────────
Each click advances ONE step. The turn only ends and passes to the opponent when:
  (a) All required steps are exhausted (steps_remaining == 0), OR
  (b) The player clicks "Stop here" after a capture (optional early stop).

Clicking a different own piece mid-turn cancels and restarts with that piece.
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Set, Tuple, FrozenSet

import pygame

from annuvin.board import Cube, HexBoard, _cube_add, CUBE_DIRECTIONS
from annuvin.constants import (
    WINDOW_WIDTH, WINDOW_HEIGHT, HEX_RADIUS,
    BG_COLOR, PANEL_COLOR, BORDER_COLOR,
    HEX_FILL, HEX_BORDER, HEX_HOVER, HEX_SELECTED,
    HEX_VALID_MOVE, HEX_LAST_MOVE, HEX_HINT, HEX_HINT_PATH,
    P1_COLOR, P2_COLOR, P1_COLOR_DARK, P2_COLOR_DARK,
    TEXT_COLOR, DIM_TEXT_COLOR, ACCENT_COLOR, WHITE, BLACK,
    BUTTON_COLOR, BUTTON_HOVER_COLOR, BUTTON_DISABLED, BUTTON_TEXT,
    PLAYER_1, PLAYER_2,
)
from annuvin.game import AnnuvinGame, Move


# ─── Geometry helpers ─────────────────────────────────────────────────────────

def _hex_corners(cx: float, cy: float, r: float) -> List[Tuple[float, float]]:
    corners = []
    for i in range(6):
        angle_rad = math.radians(60 * i)
        corners.append((cx + r * math.cos(angle_rad),
                         cy + r * math.sin(angle_rad)))
    return corners


def _pixel_in_hex(px: float, py: float, cx: float, cy: float, r: float) -> bool:
    x, y = px - cx, py - cy
    fq = (2 / 3 * x) / r
    fr = (-1 / 3 * x + math.sqrt(3) / 3 * y) / r
    return max(abs(fq), abs(fr), abs(-fq - fr)) <= 1.0


# ─── Button ───────────────────────────────────────────────────────────────────

class Button:
    def __init__(self, rect: pygame.Rect, text: str,
                 enabled: bool = True,
                 color: Tuple[int, int, int] = BUTTON_COLOR,
                 hover_color: Tuple[int, int, int] = BUTTON_HOVER_COLOR) -> None:
        self.rect        = rect
        self.text        = text
        self.enabled     = enabled
        self.color       = color
        self.hover_color = hover_color
        self._hovered    = False

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.enabled:
            return False
        if event.type == pygame.MOUSEMOTION:
            self._hovered = self.rect.collidepoint(event.pos)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                return True
        return False

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        if not self.enabled:
            pygame.draw.rect(surface, BUTTON_DISABLED, self.rect, border_radius=8)
            label = font.render(self.text, True, DIM_TEXT_COLOR)
        else:
            col = self.hover_color if self._hovered else self.color
            pygame.draw.rect(surface, col, self.rect, border_radius=8)
            label = font.render(self.text, True, BUTTON_TEXT)
        surface.blit(label, label.get_rect(center=self.rect.center))


# ─── Board renderer ───────────────────────────────────────────────────────────

class BoardRenderer:
    SIDEBAR_WIDTH = 240

    def __init__(self, surface: pygame.Surface, game: AnnuvinGame) -> None:
        self.surface = surface
        self.game    = game
        self.board   = game.board
        self._compute_origin()
        self.player_names: dict = {1: "Player 1", 2: "Player 2"}
        self.human_players: set = {1, 2}
        self.ai_think_start: float = 0.0
        self.ai_think_delay: float = 0.8

        self.hover_cell: Optional[Cube] = None

        # ── In-progress turn state ───────────────────────────────────────────
        self._turn_origin: Optional[Cube]  = None
        self._active_pos: Optional[Cube]   = None
        self._steps_remaining: int         = 0
        self._path_so_far: List[Cube]      = []
        self._captures_so_far: List[Cube]  = []
        self._just_captured: bool          = False
        self._live_opp: FrozenSet[Cube]    = frozenset()
        self._next_step_cells: Set[Cube]   = set()
        self._reachable_cells: Set[Cube]   = set()
        self._trail_cells: Set[Cube]       = set()

        # Fonts
        pygame.font.init()
        self.font_large  = pygame.font.SysFont("segoeui", 22, bold=True)
        self.font_medium = pygame.font.SysFont("segoeui", 18)
        self.font_small  = pygame.font.SysFont("segoeui", 14)
        self.font_tiny   = pygame.font.SysFont("segoeui", 12)

        # Sidebar buttons
        sw = self.SIDEBAR_WIDTH
        bw, bh = sw - 40, 40
        bx = WINDOW_WIDTH - sw + 20
        self.btn_stop = Button(
            pygame.Rect(bx, WINDOW_HEIGHT - 178, bw, bh),
            "Stop here (capture)",
            enabled=False,
            color=(40, 120, 60),
            hover_color=(60, 160, 80),
        )
        self.btn_save = Button(pygame.Rect(bx, WINDOW_HEIGHT - 118, bw, bh), "Save Game")
        self.btn_quit = Button(pygame.Rect(bx, WINDOW_HEIGHT - 62,  bw, bh), "Quit to Menu")

        # ── AI vs AI controls ────────────────────────────────────────────────
        self.is_aivsai: bool = False
        self.aivsai_paused: bool = False
        self.aivsai_speed_label: str = "Normal"
        self.on_pause_toggle: Optional[callable] = None
        self.on_speed_change: Optional[callable] = None
        self.on_step_once: Optional[callable] = None

        small_bw = (bw - 10) // 2
        self.btn_pause = Button(
            pygame.Rect(bx, WINDOW_HEIGHT - 310, small_bw, 34),
            "Pause",
            color=(100, 80, 40),
            hover_color=(130, 105, 55),
        )
        self.btn_speed = Button(
            pygame.Rect(bx + small_bw + 10, WINDOW_HEIGHT - 310, small_bw, 34),
            "Normal",
            color=(60, 80, 110),
            hover_color=(80, 105, 145),
        )
        self.btn_step = Button(
            pygame.Rect(bx, WINDOW_HEIGHT - 270, bw, 34),
            "Next Move",
            enabled=False,
            color=(60, 100, 60),
            hover_color=(80, 130, 80),
        )

        # ── Hint system ──────────────────────────────────────────────────────
        self.is_human_mode: bool = False
        self.on_hint_requested: Optional[callable] = None
        self.hint_move: Optional[Move] = None
        self.hint_thinking: bool = False

        self.btn_hint = Button(
            pygame.Rect(bx, WINDOW_HEIGHT - 270, bw, 34),
            "Hint",
            color=(140, 120, 40),
            hover_color=(170, 150, 55),
        )

        # ── Stats ────────────────────────────────────────────────────────────
        self.game_stats: Optional[dict] = None

        # Callbacks
        self.on_move_selected:  Optional[callable] = None
        self.on_save_requested: Optional[callable] = None
        self.on_quit_requested: Optional[callable] = None

    # ── Layout ────────────────────────────────────────────────────────────────

    def _compute_origin(self) -> None:
        board_area_w = WINDOW_WIDTH - self.SIDEBAR_WIDTH
        self.origin_x = board_area_w / 2
        self.origin_y = WINDOW_HEIGHT / 2

    # ── Hit testing ───────────────────────────────────────────────────────────

    def _pixel_to_cell(self, px: float, py: float) -> Optional[Cube]:
        candidate = self.board.pixel_to_cube(
            px, py, HEX_RADIUS, self.origin_x, self.origin_y)
        if candidate is None:
            return None
        cx, cy = self.board.cube_to_pixel(
            candidate, HEX_RADIUS, self.origin_x, self.origin_y)
        return candidate if _pixel_in_hex(px, py, cx, cy, HEX_RADIUS) else None

    # ── Public API ────────────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.game.game_over:
            return

        if self.btn_save.handle_event(event) and self.on_save_requested:
            self.on_save_requested()
        if self.btn_quit.handle_event(event) and self.on_quit_requested:
            self.on_quit_requested()
        if self.btn_stop.handle_event(event):
            self._commit_move()

        # AI vs AI controls
        if self.is_aivsai:
            if self.btn_pause.handle_event(event) and self.on_pause_toggle:
                self.on_pause_toggle()
            if self.btn_speed.handle_event(event) and self.on_speed_change:
                self.on_speed_change()
            if self.btn_step.handle_event(event) and self.on_step_once:
                self.on_step_once()

        # Hint button
        if self.is_human_mode and not self.is_aivsai:
            if self.btn_hint.handle_event(event) and self.on_hint_requested:
                self.on_hint_requested()

        if event.type == pygame.MOUSEMOTION:
            self.hover_cell = self._pixel_to_cell(event.pos[0], event.pos[1])
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            cell = self._pixel_to_cell(event.pos[0], event.pos[1])
            if cell is not None:
                # Clear hint when player clicks on board
                self.hint_move = None
            self._handle_cell_click(cell)

    def update(self) -> None:
        self.surface.fill(BG_COLOR)
        self._draw_sidebar()
        self._draw_board()
        self._draw_pieces()
        if self.game.game_over:
            self._draw_game_over_overlay()
        if self.ai_think_start > 0 and (time.time() - self.ai_think_start) > self.ai_think_delay:
            self._draw_thinking_indicator()

    # ── Board drawing ─────────────────────────────────────────────────────────

    def _draw_board(self) -> None:
        last_cells: Set[Cube] = set()
        if self.game.last_move and self._active_pos is None:
            last_cells = {self.game.last_move.origin,
                          self.game.last_move.destination}

        # Hint cells
        hint_origin: Optional[Cube] = None
        hint_dest: Optional[Cube] = None
        hint_path_cells: Set[Cube] = set()
        if self.hint_move and not self.game.game_over:
            hint_origin = self.hint_move.origin
            hint_dest = self.hint_move.destination
            hint_path_cells = set(self.hint_move.path)

        for cell in self.board.cells:
            cx, cy = self.board.cube_to_pixel(
                cell, HEX_RADIUS, self.origin_x, self.origin_y)
            corners = _hex_corners(cx, cy, HEX_RADIUS - 2)

            if cell == self._active_pos:
                fill = HEX_SELECTED
            elif cell in self._next_step_cells:
                fill = HEX_VALID_MOVE
            elif cell in self._reachable_cells:
                fill = (40, 100, 55)
            elif cell in self._trail_cells:
                fill = (60, 80, 140)
            elif cell == hint_origin or cell == hint_dest:
                fill = HEX_HINT
            elif cell in hint_path_cells:
                fill = HEX_HINT_PATH
            elif cell in last_cells:
                fill = HEX_LAST_MOVE
            elif cell == self.hover_cell:
                fill = HEX_HOVER
            else:
                fill = HEX_FILL

            pygame.draw.polygon(self.surface, fill, corners)
            pygame.draw.polygon(self.surface, HEX_BORDER, corners, 2)

    def _draw_pieces(self) -> None:
        piece_r       = int(HEX_RADIUS * 0.45)
        piece_r_inner = int(HEX_RADIUS * 0.28)

        captured_this_turn: set = set(self._captures_so_far)
        opp = self.game.opponent(self.game.current_player)

        for player, color, dark in [
            (PLAYER_1, P1_COLOR, P1_COLOR_DARK),
            (PLAYER_2, P2_COLOR, P2_COLOR_DARK),
        ]:
            for cell in self.game.pieces[player]:
                if player == opp and cell in captured_this_turn:
                    continue

                draw_cell = cell
                if (player == self.game.current_player
                        and cell == self._turn_origin
                        and self._active_pos is not None
                        and self._path_so_far):
                    draw_cell = self._active_pos

                cx, cy = self.board.cube_to_pixel(
                    draw_cell, HEX_RADIUS, self.origin_x, self.origin_y)
                cx, cy = int(cx), int(cy)
                pygame.draw.circle(self.surface, BLACK, (cx + 2, cy + 2), piece_r)
                pygame.draw.circle(self.surface, color, (cx, cy), piece_r)
                pygame.draw.circle(self.surface, dark,  (cx, cy), piece_r, 3)
                pygame.draw.circle(self.surface, dark,  (cx, cy), piece_r_inner)

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _draw_sidebar(self) -> None:
        sx = WINDOW_WIDTH - self.SIDEBAR_WIDTH
        pygame.draw.rect(self.surface, PANEL_COLOR,
                         pygame.Rect(sx, 0, self.SIDEBAR_WIDTH, WINDOW_HEIGHT))
        pygame.draw.line(self.surface, BORDER_COLOR, (sx, 0), (sx, WINDOW_HEIGHT), 2)

        y = 20

        title = self.font_large.render("ANNUVIN", True, ACCENT_COLOR)
        self.surface.blit(title,
            (sx + self.SIDEBAR_WIDTH // 2 - title.get_width() // 2, y))
        y += 36

        pygame.draw.line(self.surface, BORDER_COLOR,
                         (sx + 10, y), (WINDOW_WIDTH - 10, y), 1)
        y += 12

        if not self.game.game_over:
            turn_col = P1_COLOR if self.game.current_player == PLAYER_1 else P2_COLOR
            self.surface.blit(
                self.font_medium.render("Current Turn:", True, DIM_TEXT_COLOR),
                (sx + 20, y))
            y += 22
            self.surface.blit(
                self.font_large.render(self.player_names[self.game.current_player],
                                       True, turn_col),
                (sx + 20, y))
            y += 36

        # Steps display
        if not self.game.game_over:
            total = self.game.steps_for(self.game.current_player)
            if self._active_pos is not None:
                label = f"Steps left: {self._steps_remaining} / {total}"
            else:
                label = f"Steps this turn: {total}"
            self.surface.blit(
                self.font_medium.render(label, True, TEXT_COLOR),
                (sx + 20, y))
            y += 28

        pygame.draw.line(self.surface, BORDER_COLOR,
                         (sx + 10, y), (WINDOW_WIDTH - 10, y), 1)
        y += 12

        for player, color in [
            (PLAYER_1, P1_COLOR),
            (PLAYER_2, P2_COLOR),
        ]:
            name = self.player_names[player]
            self.surface.blit(
                self.font_medium.render(
                    f"{name}: {self.game.piece_count(player)} pcs",
                    True, color),
                (sx + 20, y))
            y += 26
        y += 4

        self.surface.blit(
            self.font_small.render(
                f"Move #{self.game.move_count + 1}", True, DIM_TEXT_COLOR),
            (sx + 20, y))
        y += 22

        pygame.draw.line(self.surface, BORDER_COLOR,
                         (sx + 10, y), (WINDOW_WIDTH - 10, y), 1)
        y += 10

        # Turn status hints
        if self._active_pos is not None:
            if self._captures_so_far:
                self.surface.blit(
                    self.font_small.render(
                        f"Captured: {len(self._captures_so_far)}", True, (220, 170, 60)),
                    (sx + 20, y))
                y += 20
            if self._just_captured and self._steps_remaining > 0:
                msg = "Captured! Stop or keep going"
                col = (140, 220, 100)
            elif self._steps_remaining > 0:
                msg = f"Take {self._steps_remaining} more step(s)"
                col = DIM_TEXT_COLOR
            else:
                msg = "Move complete!"
                col = ACCENT_COLOR
            self.surface.blit(
                self.font_small.render(msg, True, col),
                (sx + 20, y))
        else:
            if self.hint_thinking:
                self.surface.blit(
                    self.font_small.render("Computing hint...", True, (200, 180, 60)),
                    (sx + 20, y))
            elif self.hint_move:
                self.surface.blit(
                    self.font_small.render("Hint shown (gold)", True, (200, 180, 60)),
                    (sx + 20, y))
            else:
                self.surface.blit(
                    self.font_small.render("Click a piece to move", True, DIM_TEXT_COLOR),
                    (sx + 20, y))

        # Update button states
        self.btn_stop.enabled = (self._active_pos is not None
                                 and self._just_captured
                                 and self._steps_remaining > 0)

        # Draw AI vs AI controls OR hint button
        if self.is_aivsai and not self.game.game_over:
            self.btn_pause.text = "Play" if self.aivsai_paused else "Pause"
            self.btn_speed.text = self.aivsai_speed_label
            self.btn_step.enabled = self.aivsai_paused
            self.btn_pause.draw(self.surface, self.font_small)
            self.btn_speed.draw(self.surface, self.font_small)
            self.btn_step.draw(self.surface, self.font_small)
        elif self.is_human_mode and not self.game.game_over:
            can_hint = (self.game.current_player in self.human_players
                        and not self.hint_thinking
                        and self._active_pos is None)
            self.btn_hint.enabled = can_hint
            self.btn_hint.text = "Computing..." if self.hint_thinking else "Hint"
            self.btn_hint.draw(self.surface, self.font_small)

        self.btn_stop.draw(self.surface, self.font_medium)
        self.btn_save.draw(self.surface, self.font_medium)
        self.btn_quit.draw(self.surface, self.font_medium)

    # ── Game-over overlay ─────────────────────────────────────────────────────

    def _draw_game_over_overlay(self) -> None:
        overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.surface.blit(overlay, (0, 0))

        board_cx = (WINDOW_WIDTH - self.SIDEBAR_WIDTH) // 2

        if self.game.winner == 0:
            msg, col = "Draw!", ACCENT_COLOR
        else:
            msg = f"{self.player_names.get(self.game.winner, 'Player ' + str(self.game.winner))} Wins!"
            col = P1_COLOR if self.game.winner == PLAYER_1 else P2_COLOR

        font_big = pygame.font.SysFont("segoeui", 44, bold=True)
        font_sub = pygame.font.SysFont("segoeui", 18)
        font_stat = pygame.font.SysFont("segoeui", 15)

        t = font_big.render(msg, True, col)
        self.surface.blit(t, t.get_rect(center=(board_cx, WINDOW_HEIGHT // 2 - 100)))

        # Stats display
        if self.game_stats:
            y_stat = WINDOW_HEIGHT // 2 - 50
            # Header
            hdr = font_sub.render("Game Statistics", True, ACCENT_COLOR)
            self.surface.blit(hdr, hdr.get_rect(center=(board_cx, y_stat)))
            y_stat += 30

            for p in [1, 2]:
                p_col = P1_COLOR if p == PLAYER_1 else P2_COLOR
                s = self.game_stats[p]
                name = self.player_names.get(p, f"Player {p}")
                avg_t = s["total_time"] / s["moves"] if s["moves"] > 0 else 0.0

                name_surf = font_stat.render(f"{name}", True, p_col)
                self.surface.blit(name_surf, name_surf.get_rect(center=(board_cx, y_stat)))
                y_stat += 20

                stats_line = (f"Moves: {s['moves']}  |  Captures: {s['captures']}  |  "
                              f"Avg time: {avg_t:.2f}s  |  Pieces: {self.game.piece_count(p)}")
                stat_surf = font_stat.render(stats_line, True, WHITE)
                self.surface.blit(stat_surf, stat_surf.get_rect(center=(board_cx, y_stat)))
                y_stat += 28

            total_line = f"Total moves: {self.game.move_count}"
            total_surf = font_stat.render(total_line, True, DIM_TEXT_COLOR)
            self.surface.blit(total_surf, total_surf.get_rect(center=(board_cx, y_stat)))
            y_stat += 30
        else:
            y_stat = WINDOW_HEIGHT // 2 + 10

        s = font_sub.render("Press ENTER to return to menu", True, WHITE)
        self.surface.blit(s, s.get_rect(center=(board_cx, y_stat)))

    # ── Turn management ───────────────────────────────────────────────────────

    def _reset_turn(self) -> None:
        self._turn_origin     = None
        self._active_pos      = None
        self._steps_remaining = 0
        self._path_so_far     = []
        self._captures_so_far = []
        self._just_captured   = False
        self._live_opp        = frozenset()
        self._next_step_cells = set()
        self._reachable_cells = set()
        self._trail_cells     = set()

    def _start_turn(self, piece: Cube) -> None:
        player = self.game.current_player
        self._turn_origin     = piece
        self._active_pos      = piece
        self._steps_remaining = self.game.steps_for(player)
        self._path_so_far     = []
        self._captures_so_far = []
        self._just_captured   = False
        self._live_opp        = frozenset(
            self.game.pieces[self.game.opponent(player)])
        self._trail_cells     = set()
        self._refresh_next_steps()
        self._refresh_reachable()

    def _refresh_next_steps(self) -> None:
        if self._active_pos is None:
            self._next_step_cells = set()
            return

        player  = self.game.current_player
        own     = self.game.pieces[player]
        current = self._active_pos
        result: Set[Cube] = set()

        for d in CUBE_DIRECTIONS:
            nxt = _cube_add(current, d)
            if not self.board.is_valid(nxt):
                continue
            if nxt in own and nxt != self._turn_origin:
                continue
            result.add(nxt)

        self._next_step_cells = result

    def _refresh_reachable(self) -> None:
        if self._active_pos is None or self._steps_remaining == 0:
            self._reachable_cells = set()
            return

        own    = self.game.pieces[self.game.current_player]
        result: Set[Cube] = set()
        from collections import deque
        queue: deque = deque([(self._active_pos, self._steps_remaining)])
        visited = {self._active_pos}

        while queue:
            cell, remaining = queue.popleft()
            if remaining == 0:
                continue
            for d in CUBE_DIRECTIONS:
                nxt = _cube_add(cell, d)
                if not self.board.is_valid(nxt):
                    continue
                if nxt in own and nxt != self._turn_origin:
                    continue
                result.add(nxt)
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, remaining - 1))

        self._reachable_cells = result - self._next_step_cells

    def _take_step(self, dest: Cube) -> None:
        is_capture = dest in self._live_opp

        self._path_so_far.append(dest)
        self._trail_cells.add(dest)
        self._steps_remaining -= 1
        self._active_pos = dest

        if is_capture:
            self._captures_so_far.append(dest)
            self._live_opp = frozenset(c for c in self._live_opp if c != dest)
            self._just_captured = True
        else:
            self._just_captured = False

        if self._steps_remaining == 0:
            self._commit_move()
            return

        self._refresh_next_steps()
        self._refresh_reachable()

        if not self._next_step_cells:
            self._commit_move()

    def _commit_move(self) -> None:
        if not self._path_so_far:
            self._reset_turn()
            return

        move = Move(
            origin=self._turn_origin,
            path=list(self._path_so_far),
            captures=list(self._captures_so_far),
        )
        self._reset_turn()
        if self.on_move_selected:
            self.on_move_selected(move)

    # ── Click handling ────────────────────────────────────────────────────────

    def _handle_cell_click(self, clicked: Optional[Cube]) -> None:
        if clicked is None:
            return

        if self.game.current_player not in self.human_players:
            return

        player = self.game.current_player

        if self._active_pos is None:
            if clicked in self.game.pieces[player]:
                self._start_turn(clicked)
            return

        if clicked == self._active_pos:
            if not self._path_so_far:
                self._reset_turn()
            return

        if clicked in self.game.pieces[player] and clicked != self._turn_origin:
            self._reset_turn()
            self._start_turn(clicked)
            return

        if clicked in self._next_step_cells:
            self._take_step(clicked)
            return

    def _draw_thinking_indicator(self) -> None:
        board_area_w = WINDOW_WIDTH - self.SIDEBAR_WIDTH
        pulse = (math.sin(time.time() * 3) + 1) / 2

        overlay = pygame.Surface((board_area_w, WINDOW_HEIGHT), pygame.SRCALPHA)
        alpha = int(30 + 20 * pulse)
        overlay.fill((20, 20, 60, alpha))
        self.surface.blit(overlay, (0, 0))

        bar_h = 52
        bar_y = WINDOW_HEIGHT // 2 - bar_h // 2
        bar_alpha = int(200 + 40 * pulse)
        bar_surf = pygame.Surface((board_area_w, bar_h), pygame.SRCALPHA)
        bar_surf.fill((28, 28, 60, bar_alpha))
        self.surface.blit(bar_surf, (0, bar_y))

        dot_count = int(time.time() * 2) % 4
        dots = " ●" * dot_count
        font = pygame.font.SysFont("segoeui", 22, bold=True)
        label = font.render(f"AI is thinking{dots}", True, (180, 200, 255))
        self.surface.blit(label, label.get_rect(
            center=(board_area_w // 2, bar_y + bar_h // 2)))

        line_alpha = int(100 + 100 * pulse)
        line_col = (80, 100, 200, line_alpha)
        for ly in (bar_y, bar_y + bar_h - 1):
            line_surf = pygame.Surface((board_area_w, 2), pygame.SRCALPHA)
            line_surf.fill(line_col)
            self.surface.blit(line_surf, (0, ly))
