"""
rules_screen.py — Full rules display screen for Annuvin.

Renders the complete rules in a scrollable page.
Returns to the previous screen when the user presses ESC or clicks "Back".
"""

from __future__ import annotations

from typing import Callable, List

import pygame

from annuvin.constants import (
    WINDOW_WIDTH, WINDOW_HEIGHT,
    BG_COLOR, PANEL_COLOR, BORDER_COLOR,
    TEXT_COLOR, DIM_TEXT_COLOR, ACCENT_COLOR, WHITE,
    BUTTON_COLOR, BUTTON_HOVER_COLOR,
    P1_COLOR, P2_COLOR,
)

# ─── Rule text ────────────────────────────────────────────────────────────────

RULES_SECTIONS = [
    {
        "title": "Overview",
        "body": (
            "Annuvin is a two-player abstract strategy game played on a "
            "hexagonal board (HexHex-4: 4 hexagons per side, 37 cells total). "
            "Each player controls 6 stones placed in opposite corner clusters "
            "at the start of the game."
        ),
    },
    {
        "title": "Objective",
        "body": (
            "Win by achieving EITHER of the following:\n"
            "  1. Capture all 6 of your opponent's stones.\n"
            "  2. Reduce your opponent to exactly 1 stone while you still have "
            "all 6 of your own stones intact."
        ),
    },
    {
        "title": "Setup",
        "body": (
            "Player 1 (Red) occupies one corner cluster of 6 cells.\n"
            "Player 2 (Blue) occupies the diagonally opposite corner cluster "
            "of 6 cells.\n"
            "Player 1 always moves first."
        ),
    },
    {
        "title": "Movement Allowance",
        "body": (
            "Each turn, a player moves exactly ONE of their stones.\n"
            "The number of steps allowed depends on how many stones the "
            "active player has remaining:\n\n"
            "  6 stones → 1 step per turn\n"
            "  5 stones → 2 steps per turn\n"
            "  4 stones → 3 steps per turn\n"
            "  3 stones → 4 steps per turn\n"
            "  2 stones → 5 steps per turn\n"
            "  1 stone  → 6 steps per turn\n\n"
            "Note: as you lose pieces you gain more steps — the game "
            "becomes more dynamic with fewer pieces!"
        ),
    },
    {
        "title": "How Movement Works",
        "body": (
            "A stone moves one adjacent hex cell per step and may change "
            "direction freely between steps.\n\n"
            "A stone CANNOT move through its own pieces; they block movement.\n\n"
            "A stone MUST use ALL of its allotted steps each turn — "
            "you cannot voluntarily stop on an empty cell before exhausting "
            "your steps.\n\n"
            "Exception: a stone may stop early ONLY if it just made a capture "
            "(it may choose to forfeit any remaining steps after a capture)."
        ),
    },
    {
        "title": "Captures",
        "body": (
            "A stone captures an opponent's piece by stepping onto the cell "
            "that piece occupies.\n\n"
            "After a capture, the moving stone MAY continue using its "
            "remaining steps to make further captures — or it may stop.\n\n"
            "A stone CANNOT end its turn on a cell occupied by one of its "
            "own pieces.\n\n"
            "There is NO jumping over pieces; movement is always step-by-step "
            "along adjacent hexes."
        ),
    },
    {
        "title": "Forbidden Moves",
        "body": (
            "The following moves are NOT allowed and will be rejected by "
            "the game:\n\n"
            "  • Moving a piece that does not belong to the active player.\n"
            "  • Stopping on an empty cell before using all available steps "
            "(unless a capture was made).\n"
            "  • Moving through or onto a cell occupied by a friendly piece.\n"
            "  • Moving to a cell outside the board.\n"
            "  • Skipping your turn (you must move if a legal move exists)."
        ),
    },
    {
        "title": "Draw Condition",
        "body": (
            "The game ends in a draw if 150 half-moves (turns) are played "
            "without a winner being decided.\n\n"
            "No other draw condition is defined in the official rules."
        ),
    },
    {
        "title": "Controls",
        "body": (
            "Mouse click on one of YOUR pieces → selects that piece.\n"
            "Green-highlighted cells show where the selected piece can legally move.\n"
            "Click a green cell → executes the move.\n"
            "Click the selected piece again → deselects it.\n"
            "Click a different own piece → switches selection.\n\n"
            "When multiple paths lead to the same destination, the game "
            "automatically picks the path that captures the most opponent "
            "pieces."
        ),
    },
]

# ─── Screen ───────────────────────────────────────────────────────────────────

class RulesScreen:
    """
    Scrollable rules display.

    Parameters
    ----------
    surface      : pygame.Surface
    on_back      : callable — invoked when the user returns to the previous screen
    """

    LINE_HEIGHT      = 22
    SECTION_GAP      = 18
    TITLE_HEIGHT     = 32
    SIDE_PADDING     = 60
    TOP_PADDING      = 80
    BOTTOM_PADDING   = 100
    SCROLL_SPEED     = 30

    def __init__(self, surface: pygame.Surface, on_back: Callable) -> None:
        self.surface  = surface
        self.on_back  = on_back
        self._scroll  = 0
        self._max_scroll = 0

        pygame.font.init()
        self.font_title   = pygame.font.SysFont("segoeui", 26, bold=True)
        self.font_section = pygame.font.SysFont("segoeui", 18, bold=True)
        self.font_body    = pygame.font.SysFont("segoeui", 16)
        self.font_hint    = pygame.font.SysFont("segoeui", 14)

        # Back button
        bw, bh = 160, 42
        bx = WINDOW_WIDTH // 2 - bw // 2
        by = WINDOW_HEIGHT - 60
        self._btn_back = _RulesButton(pygame.Rect(bx, by, bw, bh), "← Back to Menu")

        self._pre_render_content()

    def _pre_render_content(self) -> None:
        """Pre-render text surfaces and record their y positions."""
        self._entries: List[tuple] = []   # (y, surface)
        usable_w = WINDOW_WIDTH - 2 * self.SIDE_PADDING

        y = self.TOP_PADDING

        # Page title
        title_surf = self.font_title.render("Annuvin — Rules & Guide", True, ACCENT_COLOR)
        self._entries.append((y, title_surf))
        y += self.TITLE_HEIGHT + 10

        # Under-title rule line marker
        self._title_line_y = y
        y += 14

        for section in RULES_SECTIONS:
            # Section heading
            heading_surf = self.font_section.render(
                f"▸  {section['title']}", True, P1_COLOR)
            self._entries.append((y, heading_surf))
            y += self.TITLE_HEIGHT

            # Body text — word-wrap
            body_lines = self._wrap_text(section["body"], self.font_body, usable_w)
            for line in body_lines:
                line_surf = self.font_body.render(line, True, TEXT_COLOR)
                self._entries.append((y, line_surf))
                y += self.LINE_HEIGHT

            y += self.SECTION_GAP

        self._content_height = y + self.BOTTOM_PADDING
        self._max_scroll = max(0, self._content_height - WINDOW_HEIGHT + 80)

    def _wrap_text(self, text: str, font: pygame.font.Font, max_w: int) -> List[str]:
        """Wrap *text* to fit within *max_w* pixels; honours '\\n' line breaks."""
        result: List[str] = []
        for paragraph in text.split("\n"):
            if paragraph.strip() == "":
                result.append("")
                continue
            words = paragraph.split(" ")
            line  = ""
            for word in words:
                test = (line + " " + word).strip()
                if font.size(test)[0] <= max_w:
                    line = test
                else:
                    if line:
                        result.append(line)
                    line = word
            if line:
                result.append(line)
        return result

    # ── Event handling ────────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> None:
        if self._btn_back.handle_event(event):
            self.on_back()

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self.on_back()
            elif event.key == pygame.K_DOWN:
                self._scroll = min(self._scroll + self.SCROLL_SPEED, self._max_scroll)
            elif event.key == pygame.K_UP:
                self._scroll = max(self._scroll - self.SCROLL_SPEED, 0)

        if event.type == pygame.MOUSEWHEEL:
            self._scroll -= event.y * self.SCROLL_SPEED
            self._scroll = max(0, min(self._scroll, self._max_scroll))

    # ── Rendering ─────────────────────────────────────────────────────────────

    def update(self) -> None:
        self.surface.fill(BG_COLOR)
        self._draw_background_panel()
        self._draw_entries()
        self._draw_scroll_indicator()
        self._draw_footer()

    def _draw_background_panel(self) -> None:
        panel = pygame.Rect(20, 10, WINDOW_WIDTH - 40, WINDOW_HEIGHT - 80)
        pygame.draw.rect(self.surface, PANEL_COLOR, panel, border_radius=12)
        pygame.draw.rect(self.surface, BORDER_COLOR, panel, 2, border_radius=12)

    def _draw_entries(self) -> None:
        clip_top = 20
        clip_bottom = WINDOW_HEIGHT - 80
        for (y_abs, surf) in self._entries:
            y = y_abs - self._scroll
            if y + surf.get_height() < clip_top:
                continue
            if y > clip_bottom:
                break
            self.surface.blit(surf, (self.SIDE_PADDING, y))

        # Draw horizontal rule under page title
        rule_y = self._title_line_y - self._scroll
        if clip_top < rule_y < clip_bottom:
            pygame.draw.line(self.surface, BORDER_COLOR,
                             (self.SIDE_PADDING, rule_y),
                             (WINDOW_WIDTH - self.SIDE_PADDING, rule_y), 1)

    def _draw_scroll_indicator(self) -> None:
        if self._max_scroll <= 0:
            return
        track_h = WINDOW_HEIGHT - 140
        track_x = WINDOW_WIDTH - 28
        track_y = 70
        pygame.draw.rect(self.surface, PANEL_COLOR,
                         pygame.Rect(track_x - 4, track_y, 8, track_h),
                         border_radius=4)
        ratio = self._scroll / self._max_scroll if self._max_scroll > 0 else 0
        thumb_h = max(30, int(track_h * (WINDOW_HEIGHT / self._content_height)))
        thumb_y = track_y + int((track_h - thumb_h) * ratio)
        pygame.draw.rect(self.surface, ACCENT_COLOR,
                         pygame.Rect(track_x - 4, thumb_y, 8, thumb_h),
                         border_radius=4)

    def _draw_footer(self) -> None:
        # Footer bar
        footer_rect = pygame.Rect(0, WINDOW_HEIGHT - 72, WINDOW_WIDTH, 72)
        pygame.draw.rect(self.surface, PANEL_COLOR, footer_rect)
        pygame.draw.line(self.surface, BORDER_COLOR,
                         (0, WINDOW_HEIGHT - 72), (WINDOW_WIDTH, WINDOW_HEIGHT - 72), 1)

        self._btn_back.draw(self.surface, self.font_body)

        hint_surf = self.font_hint.render(
            "Scroll: mouse wheel or ↑ ↓ keys  |  ESC to go back", True, DIM_TEXT_COLOR)
        self.surface.blit(hint_surf,
                          (WINDOW_WIDTH // 2 - hint_surf.get_width() // 2,
                           WINDOW_HEIGHT - 22))


# ─── Simple button for this screen ───────────────────────────────────────────

class _RulesButton:
    def __init__(self, rect: pygame.Rect, text: str) -> None:
        self.rect    = rect
        self.text    = text
        self._hovered = False

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEMOTION:
            self._hovered = self.rect.collidepoint(event.pos)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                return True
        return False

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        col = BUTTON_HOVER_COLOR if self._hovered else BUTTON_COLOR
        pygame.draw.rect(surface, col, self.rect, border_radius=8)
        label = font.render(self.text, True, WHITE)
        surface.blit(label, label.get_rect(center=self.rect.center))
