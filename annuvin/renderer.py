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
from typing import Dict, List, Optional, Set, Tuple, FrozenSet

import pygame

from annuvin.board import Cube, HexBoard, _cube_add, CUBE_DIRECTIONS
from annuvin.constants import (
    WINDOW_WIDTH, WINDOW_HEIGHT, HEX_RADIUS,
    BG_COLOR, PANEL_COLOR, BORDER_COLOR,
    HEX_FILL, HEX_BORDER, HEX_HOVER, HEX_SELECTED,
    HEX_VALID_MOVE, HEX_LAST_MOVE,
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

        self.hover_cell: Optional[Cube] = None

        # ── In-progress turn state ───────────────────────────────────────────
        # _turn_origin: the cell where the selected piece started THIS turn
        # _active_pos:  the cell where the piece currently is (updated per step)
        self._turn_origin: Optional[Cube]  = None
        self._active_pos: Optional[Cube]   = None
        self._steps_remaining: int         = 0
        self._path_so_far: List[Cube]      = []     # steps taken so far
        self._captures_so_far: List[Cube]  = []     # cells of captured pieces
        self._just_captured: bool          = False  # last step was a capture?
        self._live_opp: FrozenSet[Cube]    = frozenset()
        self._next_step_cells: Set[Cube]   = set()
        self._reachable_cells: Set[Cube]   = set()  # BFS flood for dim hints
        self._trail_cells: Set[Cube]       = set()  # visual trail

        # Fonts
        pygame.font.init()
        self.font_large  = pygame.font.SysFont("segoeui", 22, bold=True)
        self.font_medium = pygame.font.SysFont("segoeui", 18)
        self.font_small  = pygame.font.SysFont("segoeui", 14)

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

        if event.type == pygame.MOUSEMOTION:
            self.hover_cell = self._pixel_to_cell(event.pos[0], event.pos[1])
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._handle_cell_click(self._pixel_to_cell(event.pos[0], event.pos[1]))

    def update(self) -> None:
        self.surface.fill(BG_COLOR)
        self._draw_sidebar()
        self._draw_board()
        self._draw_pieces()
        if self.game.game_over:
            self._draw_game_over_overlay()

    # ── Board drawing ─────────────────────────────────────────────────────────

    def _draw_board(self) -> None:
        last_cells: Set[Cube] = set()
        if self.game.last_move and self._active_pos is None:
            last_cells = {self.game.last_move.origin,
                          self.game.last_move.destination}

        for cell in self.board.cells:
            cx, cy = self.board.cube_to_pixel(
                cell, HEX_RADIUS, self.origin_x, self.origin_y)
            corners = _hex_corners(cx, cy, HEX_RADIUS - 2)

            if cell == self._active_pos:
                fill = HEX_SELECTED
            elif cell in self._next_step_cells:
                fill = HEX_VALID_MOVE
            elif cell in self._reachable_cells:
                fill = (40, 100, 55)        # dim green — reachable but not immediate
            elif cell in self._trail_cells:
                fill = (60, 80, 140)        # blue-grey trail
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

        # Enemy pieces already taken this turn — hide them immediately on capture
        captured_this_turn: set = set(self._captures_so_far)
        opp = self.game.opponent(self.game.current_player)

        for player, color, dark in [
            (PLAYER_1, P1_COLOR, P1_COLOR_DARK),
            (PLAYER_2, P2_COLOR, P2_COLOR_DARK),
        ]:
            for cell in self.game.pieces[player]:
                # Hide enemy pieces captured mid-turn (game.pieces not updated yet)
                if player == opp and cell in captured_this_turn:
                    continue

                # The active piece is stored at _turn_origin in game.pieces;
                # draw it at _active_pos (its current visual position) instead.
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
                self.font_large.render(f"Player {self.game.current_player}",
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

        for player, color, name in [
            (PLAYER_1, P1_COLOR, "Player 1"),
            (PLAYER_2, P2_COLOR, "Player 2"),
        ]:
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
            self.surface.blit(
                self.font_small.render("Click a piece to move", True, DIM_TEXT_COLOR),
                (sx + 20, y))

        # Update button states
        self.btn_stop.enabled   = (self._active_pos is not None
                                   and self._just_captured
                                   and self._steps_remaining > 0)

        self.btn_stop.draw(self.surface, self.font_medium)
        self.btn_save.draw(self.surface, self.font_medium)
        self.btn_quit.draw(self.surface, self.font_medium)

    # ── Game-over overlay ─────────────────────────────────────────────────────

    def _draw_game_over_overlay(self) -> None:
        overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.surface.blit(overlay, (0, 0))

        if self.game.winner == 0:
            msg, col = "Draw!", ACCENT_COLOR
        else:
            msg = f"Player {self.game.winner} Wins!"
            col = P1_COLOR if self.game.winner == PLAYER_1 else P2_COLOR

        font_big = pygame.font.SysFont("segoeui", 52, bold=True)
        font_sub = pygame.font.SysFont("segoeui", 22)
        t = font_big.render(msg, True, col)
        self.surface.blit(t, t.get_rect(
            center=(WINDOW_WIDTH // 2 - self.SIDEBAR_WIDTH // 2,
                    WINDOW_HEIGHT // 2 - 30)))
        s = font_sub.render("Press ENTER to return to menu", True, WHITE)
        self.surface.blit(s, s.get_rect(
            center=(WINDOW_WIDTH // 2 - self.SIDEBAR_WIDTH // 2,
                    WINDOW_HEIGHT // 2 + 30)))

    # ── Turn management ───────────────────────────────────────────────────────

    def _reset_turn(self) -> None:
        """Abandon in-progress turn, return to piece-selection state."""
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
        """Begin a new turn for *piece*."""
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
        """Compute the set of cells the active piece can step to in ONE step."""
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
            # Cannot enter a cell occupied by an own piece
            # (the piece that is currently moving started at _turn_origin;
            #  its spot in game.pieces is still the origin, so exclude it only
            #  if it's a *different* own piece)
            if nxt in own and nxt != self._turn_origin:
                continue
            result.add(nxt)

        self._next_step_cells = result

    def _refresh_reachable(self) -> None:
        """BFS flood-fill up to _steps_remaining hops — shown as dim green hints."""
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

        # Remove the immediate next-step cells — they already have their own highlight
        self._reachable_cells = result - self._next_step_cells

    def _take_step(self, dest: Cube) -> None:
        """Advance the active piece one step to *dest*."""
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

        # Auto-commit: no steps left
        if self._steps_remaining == 0:
            self._commit_move()
            return

        # Refresh valid next-step cells and reachable area
        self._refresh_next_steps()
        self._refresh_reachable()

        # Auto-commit: completely blocked with steps remaining (forced stop)
        if not self._next_step_cells:
            self._commit_move()

    def _commit_move(self) -> None:
        """Apply the accumulated path as a Move to the game."""
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

        player = self.game.current_player

        # ── No piece in progress: select a piece ─────────────────────────────
        if self._active_pos is None:
            if clicked in self.game.pieces[player]:
                self._start_turn(clicked)
            return

        # ── Turn in progress ─────────────────────────────────────────────────

        # Clicking the active piece's current cell:
        #   - If no steps taken yet → deselect (cancel before first step)
        #   - If steps taken → ignore (can't go back)
        if clicked == self._active_pos:
            if not self._path_so_far:
                self._reset_turn()
            return

        # Clicking a different OWN piece → cancel and start fresh with it
        if clicked in self.game.pieces[player] and clicked != self._turn_origin:
            self._reset_turn()
            self._start_turn(clicked)
            return

        # Clicking a valid next-step destination → take the step
        if clicked in self._next_step_cells:
            self._take_step(clicked)
            return

        # Anything else → ignore