"""
renderer.py — Pygame rendering of the Annuvin board and game state.

Responsibilities:
• Draw the hex grid with flat-top hexagons.
• Draw player pieces as circles inside hexes.
• Highlight the selected piece, its valid destinations, and the last move made.
• Show a sidebar with current turn, piece counts, and action buttons.
• Handle mouse → cell coordinate mapping.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Set, Tuple

import pygame

from annuvin.board import Cube, HexBoard
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
    """Return the 6 corner pixel positions of a flat-top hexagon."""
    corners = []
    for i in range(6):
        angle_deg = 60 * i           # flat-top: starts at 0°
        angle_rad = math.radians(angle_deg)
        corners.append((cx + r * math.cos(angle_rad),
                         cy + r * math.sin(angle_rad)))
    return corners


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
        """Return True if button was clicked."""
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
    """
    Manages all drawing for an in-progress Annuvin game.

    Call update() every frame.  Returns user actions via handle_event().
    """

    SIDEBAR_WIDTH = 240

    def __init__(self, surface: pygame.Surface, game: AnnuvinGame) -> None:
        self.surface  = surface
        self.game     = game
        self.board    = game.board
        self._compute_origin()

        # Interaction state
        self.selected_cell: Optional[Cube]       = None
        self.valid_moves_for_selected: List[Move] = []
        self.hover_cell: Optional[Cube]          = None

        # Fonts
        pygame.font.init()
        self.font_large  = pygame.font.SysFont("segoeui", 22, bold=True)
        self.font_medium = pygame.font.SysFont("segoeui", 18)
        self.font_small  = pygame.font.SysFont("segoeui", 14)

        # Sidebar buttons
        sw = self.SIDEBAR_WIDTH
        bw, bh = sw - 40, 40
        bx = WINDOW_WIDTH - sw + 20
        self.btn_save = Button(pygame.Rect(bx, WINDOW_HEIGHT - 160, bw, bh), "Save Game")
        self.btn_quit = Button(pygame.Rect(bx, WINDOW_HEIGHT - 100, bw, bh), "Quit to Menu")

        # Callback hooks (set by the game scene)
        self.on_move_selected: Optional[callable] = None   # (Move) -> None
        self.on_save_requested: Optional[callable]= None   # () -> None
        self.on_quit_requested: Optional[callable]= None   # () -> None

    # ── Layout ────────────────────────────────────────────────────────────────

    def _compute_origin(self) -> None:
        """Centre the board in the left area (excluding sidebar)."""
        board_area_w = WINDOW_WIDTH - self.SIDEBAR_WIDTH
        self.origin_x = board_area_w / 2
        self.origin_y = WINDOW_HEIGHT / 2

    # ── Public API ────────────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.game.game_over:
            return

        # Sidebar buttons
        if self.btn_save.handle_event(event) and self.on_save_requested:
            self.on_save_requested()
        if self.btn_quit.handle_event(event) and self.on_quit_requested:
            self.on_quit_requested()

        if event.type == pygame.MOUSEMOTION:
            self.hover_cell = self.board.pixel_to_cube(
                event.pos[0], event.pos[1], HEX_RADIUS,
                self.origin_x, self.origin_y
            )

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            clicked = self.board.pixel_to_cube(
                event.pos[0], event.pos[1], HEX_RADIUS,
                self.origin_x, self.origin_y
            )
            self._handle_cell_click(clicked)

    def update(self) -> None:
        """Draw the full scene."""
        self.surface.fill(BG_COLOR)
        self._draw_sidebar()
        self._draw_board()
        self._draw_pieces()
        if self.game.game_over:
            self._draw_game_over_overlay()

    # ── Board drawing ─────────────────────────────────────────────────────────

    def _draw_board(self) -> None:
        last_cells: Set[Cube] = set()
        if self.game.last_move:
            last_cells = {self.game.last_move.origin, self.game.last_move.destination}

        valid_dests: Set[Cube] = {m.destination for m in self.valid_moves_for_selected}

        for cell in self.board.cells:
            cx, cy = self.board.cube_to_pixel(
                cell, HEX_RADIUS, self.origin_x, self.origin_y)
            corners = _hex_corners(cx, cy, HEX_RADIUS - 2)

            # Choose fill colour
            if cell == self.selected_cell:
                fill = HEX_SELECTED
            elif cell in valid_dests:
                fill = HEX_VALID_MOVE
            elif cell in last_cells:
                fill = HEX_LAST_MOVE
            elif cell == self.hover_cell:
                fill = HEX_HOVER
            else:
                fill = HEX_FILL

            pygame.draw.polygon(self.surface, fill, corners)
            pygame.draw.polygon(self.surface, HEX_BORDER, corners, 2)

    def _draw_pieces(self) -> None:
        piece_r = int(HEX_RADIUS * 0.45)
        piece_r_inner = int(HEX_RADIUS * 0.28)

        for player, color, dark in [
            (PLAYER_1, P1_COLOR, P1_COLOR_DARK),
            (PLAYER_2, P2_COLOR, P2_COLOR_DARK),
        ]:
            for cell in self.game.pieces[player]:
                cx, cy = self.board.cube_to_pixel(
                    cell, HEX_RADIUS, self.origin_x, self.origin_y)
                cx, cy = int(cx), int(cy)
                # Shadow
                pygame.draw.circle(self.surface, BLACK, (cx + 2, cy + 2), piece_r)
                # Body
                pygame.draw.circle(self.surface, color, (cx, cy), piece_r)
                # Highlight
                pygame.draw.circle(self.surface, dark, (cx, cy), piece_r, 3)
                # Inner dot
                pygame.draw.circle(self.surface, dark, (cx, cy), piece_r_inner)

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _draw_sidebar(self) -> None:
        sx = WINDOW_WIDTH - self.SIDEBAR_WIDTH
        sidebar_rect = pygame.Rect(sx, 0, self.SIDEBAR_WIDTH, WINDOW_HEIGHT)
        pygame.draw.rect(self.surface, PANEL_COLOR, sidebar_rect)
        pygame.draw.line(self.surface, BORDER_COLOR, (sx, 0), (sx, WINDOW_HEIGHT), 2)

        y = 30
        # Title
        title = self.font_large.render("ANNUVIN", True, ACCENT_COLOR)
        self.surface.blit(title, (sx + self.SIDEBAR_WIDTH // 2 - title.get_width() // 2, y))
        y += 40

        # Divider
        pygame.draw.line(self.surface, BORDER_COLOR, (sx + 10, y), (WINDOW_WIDTH - 10, y), 1)
        y += 15

        # Current turn
        if not self.game.game_over:
            turn_col = P1_COLOR if self.game.current_player == PLAYER_1 else P2_COLOR
            pname = f"Player {self.game.current_player}"
            txt = self.font_medium.render("Current Turn:", True, DIM_TEXT_COLOR)
            self.surface.blit(txt, (sx + 20, y))
            y += 24
            txt2 = self.font_large.render(pname, True, turn_col)
            self.surface.blit(txt2, (sx + 20, y))
            y += 40

        # Steps available
        if not self.game.game_over:
            steps = self.game.steps_for(self.game.current_player)
            stxt = self.font_medium.render(f"Steps this turn: {steps}", True, TEXT_COLOR)
            self.surface.blit(stxt, (sx + 20, y))
            y += 35

        # Divider
        pygame.draw.line(self.surface, BORDER_COLOR, (sx + 10, y), (WINDOW_WIDTH - 10, y), 1)
        y += 15

        # Piece counts
        for player, color, name in [
            (PLAYER_1, P1_COLOR, "Player 1"),
            (PLAYER_2, P2_COLOR, "Player 2"),
        ]:
            count = self.game.piece_count(player)
            label = self.font_medium.render(f"{name}: {count} pieces", True, color)
            self.surface.blit(label, (sx + 20, y))
            y += 28
        y += 10

        # Move counter
        mc = self.font_small.render(f"Move #{self.game.move_count + 1}", True, DIM_TEXT_COLOR)
        self.surface.blit(mc, (sx + 20, y))
        y += 25

        # Selected piece info
        if self.selected_cell and not self.game.game_over:
            pygame.draw.line(self.surface, BORDER_COLOR,
                             (sx + 10, y), (WINDOW_WIDTH - 10, y), 1)
            y += 12
            sel_txt = self.font_small.render("Selected piece", True, ACCENT_COLOR)
            self.surface.blit(sel_txt, (sx + 20, y))
            y += 20
            opt_txt = self.font_small.render(
                f"{len(self.valid_moves_for_selected)} valid moves", True, TEXT_COLOR)
            self.surface.blit(opt_txt, (sx + 20, y))
            y += 30
            esc_txt = self.font_small.render("Click again to deselect", True, DIM_TEXT_COLOR)
            self.surface.blit(esc_txt, (sx + 20, y))

        # Buttons
        self.btn_save.draw(self.surface, self.font_medium)
        self.btn_quit.draw(self.surface, self.font_medium)

    # ── Game-over overlay ─────────────────────────────────────────────────────

    def _draw_game_over_overlay(self) -> None:
        overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.surface.blit(overlay, (0, 0))

        if self.game.winner == 0:
            msg = "Draw!"
            col = ACCENT_COLOR
        else:
            msg = f"Player {self.game.winner} Wins!"
            col = P1_COLOR if self.game.winner == PLAYER_1 else P2_COLOR

        font_big = pygame.font.SysFont("segoeui", 52, bold=True)
        font_sub = pygame.font.SysFont("segoeui", 22)
        text_surf = font_big.render(msg, True, col)
        self.surface.blit(text_surf, text_surf.get_rect(
            center=(WINDOW_WIDTH // 2 - self.SIDEBAR_WIDTH // 2,
                    WINDOW_HEIGHT // 2 - 30)))
        sub_surf = font_sub.render("Press ENTER to return to menu", True, WHITE)
        self.surface.blit(sub_surf, sub_surf.get_rect(
            center=(WINDOW_WIDTH // 2 - self.SIDEBAR_WIDTH // 2,
                    WINDOW_HEIGHT // 2 + 30)))

    # ── Click handling (piece selection & move execution) ─────────────────────

    def _handle_cell_click(self, clicked: Optional[Cube]) -> None:
        if clicked is None:
            return
        player = self.game.current_player

        # Case 1: no piece selected yet
        if self.selected_cell is None:
            if clicked in self.game.pieces[player]:
                self._select(clicked)
            return

        # Case 2: clicking the same cell → deselect
        if clicked == self.selected_cell:
            self._deselect()
            return

        # Case 3: clicking another own piece → reselect
        if clicked in self.game.pieces[player]:
            self._select(clicked)
            return

        # Case 4: attempt a move to the clicked destination
        candidates = [m for m in self.valid_moves_for_selected
                      if m.destination == clicked]
        if not candidates:
            # Invalid destination — do nothing
            return

        if len(candidates) == 1:
            self._execute_move(candidates[0])
        else:
            # Multiple paths lead to the same destination.
            # Prefer the one with the most captures; if still tied, take first.
            best = max(candidates, key=lambda m: len(m.captures))
            self._execute_move(best)

    def _select(self, cell: Cube) -> None:
        self.selected_cell = cell
        player = self.game.current_player
        all_legal = self.game.legal_moves(player)
        self.valid_moves_for_selected = [m for m in all_legal if m.origin == cell]

    def _deselect(self) -> None:
        self.selected_cell = None
        self.valid_moves_for_selected = []

    def _execute_move(self, move: Move) -> None:
        if self.on_move_selected:
            self.on_move_selected(move)
        self._deselect()
