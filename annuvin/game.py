"""
game.py — Annuvin game logic and rules engine.

Rules (from BoardGameGeek / official site):
────────────────────────────────────────────
Board   : HexHex-4 hexagonal grid (37 cells).
Pieces  : 6 per player, placed in opposite corners at game start.
Goal    : Capture all opponent pieces  -OR-  reduce the opponent to exactly
          one stone while you still have all your pieces.

Movement allowance (steps per turn = 7 − number_of_your_remaining_pieces):
  6 pieces → 1 step
  5 pieces → 2 steps
  4 pieces → 3 steps
  3 pieces → 4 steps
  2 pieces → 5 steps
  1 piece  → 6 steps

A "step" is moving to an immediately adjacent hex cell (one of 6 directions).
Within a single turn a stone may change direction freely across its allotted
steps (it may also NOT pass through cells occupied by own pieces).

Captures:
  • Moving onto a cell occupied by an opponent captures that piece.
  • After a capture the moving stone MAY stop early (forfeit remaining steps)
    OR continue spending its remaining steps for further captures.
  • A stone CANNOT end its turn on a cell occupied by one of its own pieces.
  • A stone CANNOT voluntarily stop mid-move on an empty cell — it MUST use
    ALL remaining steps unless it just captured.

Special rule — mandatory use of all steps:
  The player MUST move a stone using ALL of its allotted steps unless:
    (a) The stone just made a capture (may stop after capture), OR
    (b) All further movement would be completely blocked.

Win conditions:
  1. A player captures every opponent piece.
  2. A player reduces the opponent to exactly 1 stone while still having all 6
     of their own pieces intact.

Draw: 150-move limit to avoid infinite games.
"""

from __future__ import annotations

import copy
import random
import time
import threading
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from annuvin.board import HexBoard, Cube, _cube_add, CUBE_DIRECTIONS

DRAW_MOVE_LIMIT = 150   # half-moves before automatic draw

sys.setrecursionlimit(10000)


# ─── AI logging ──────────────────────────────────────────────────────────────

class AILogger:
    """Append AI decision traces to a text file."""

    def __init__(self, filepath: str, clear: bool = False) -> None:
        self.path = Path(filepath)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if clear:
            self.path.write_text("", encoding="utf-8")

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)

# ─── Data transfer objects ────────────────────────────────────────────────────

@dataclass
class Move:
    """A complete move: a piece at *origin* following a sequence of *path* cells."""
    origin: Cube
    path: List[Cube]          # list of cells visited in order (length == steps used)
    captures: List[Cube]      # cells where enemy pieces are taken

    @property
    def destination(self) -> Cube:
        return self.path[-1]

    def __repr__(self) -> str:
        return f"Move({self.origin} → {self.destination}, caps={self.captures})"


# ─── Game state ────────────────────────────────────────────────────────────────

class AnnuvinGame:
    """
    Holds the mutable game state and enforces all rules.
    """

    def __init__(self, board: Optional[HexBoard] = None) -> None:
        self.board: HexBoard = board or HexBoard(size=4)
        init = self.board.initial_positions()
        self.pieces: Dict[int, Set[Cube]] = {
            1: set(init[1]),
            2: set(init[2]),
        }
        self.current_player: int = 1
        self.move_count: int = 0
        self.history: List[Tuple[int, Move]] = []
        self.winner: Optional[int] = None
        self.game_over: bool = False
        self.last_move: Optional[Move] = None

    # ── Derived helpers ───────────────────────────────────────────────────────

    def piece_count(self, player: int) -> int:
        return len(self.pieces[player])

    def steps_for(self, player: int) -> int:
        """Return the number of steps this player may use this turn."""
        return 7 - self.piece_count(player)

    def opponent(self, player: int) -> int:
        return 2 if player == 1 else 1

    def all_pieces(self) -> Set[Cube]:
        return self.pieces[1] | self.pieces[2]

    # ── Move generation ───────────────────────────────────────────────────────

    def legal_moves(self, player: Optional[int] = None, max_moves=200) -> List[Move]:
        """Return every legal move for *player* (defaults to current_player)."""
        if player is None:
            player = self.current_player
        steps = self.steps_for(player)
        adjusted_max = max(1, min(max_moves, max(30, max_moves // steps)))
        moves: List[Move] = []
        for origin in list(self.pieces[player]):
            self._expand_paths(
                player=player,
                origin=origin,
                current=origin,
                steps_left=steps,
                current_path=[],
                captures_so_far=[],
                live_opp=frozenset(self.pieces[self.opponent(player)]),
                own_pieces=frozenset(self.pieces[player]),
                just_captured=False,
                results=moves,
            )
            if len(moves) >= adjusted_max:
                break
        return moves

    def _expand_paths(
        self,
        player: int,
        origin: Cube,
        current: Cube,
        steps_left: int,
        current_path: List[Cube],
        captures_so_far: List[Cube],
        live_opp: FrozenSet[Cube],      # enemy pieces still alive on this path
        own_pieces: FrozenSet[Cube],
        just_captured: bool,            # did the LAST step make a capture?
        results: List[Move],
    ) -> None:
        """
        Recursive DFS to build all valid complete paths for a stone.

        STOPPING RULES (both must be satisfied to record a move):
          1. steps_left == 0  (used all allowance), OR
          2. just_captured == True AND steps_left > 0
             (player MAY choose to stop after a capture)

        Stopping on an EMPTY cell before exhausting steps is NEVER allowed.
        """

        # ── Can we stop here? ────────────────────────────────────────────────
        if current_path:   # must have moved at least once
            if steps_left == 0:
                # Used all steps — this is a valid terminal position
                # (we're guaranteed not to be on own piece because we
                #  block own-piece steps in the expansion below)
                results.append(Move(
                    origin=origin,
                    path=list(current_path),
                    captures=list(captures_so_far),
                ))
                return   # cannot continue — no steps left

            if just_captured:
                # After a capture the player MAY stop early
                results.append(Move(
                    origin=origin,
                    path=list(current_path),
                    captures=list(captures_so_far),
                ))
                # … but also fall through to explore further steps

        if steps_left == 0:
            # No path recorded yet (origin == current, shouldn't happen normally)
            return

        # ── Explore next steps ───────────────────────────────────────────────
        moved_anywhere = False
        for direction in CUBE_DIRECTIONS:
            nxt = _cube_add(current, direction)

            # Must stay on board
            if not self.board.is_valid(nxt):
                continue

            # Cannot move onto / through own pieces
            # (own pieces block movement completely in Annuvin)
            if nxt in own_pieces and nxt != origin:
                continue

            moved_anywhere = True

            # Determine if this step is a capture
            is_capture = nxt in live_opp
            new_captures = list(captures_so_far)
            new_live_opp = live_opp

            if is_capture:
                new_captures.append(nxt)
                new_live_opp = frozenset(c for c in live_opp if c != nxt)

            self._expand_paths(
                player=player,
                origin=origin,
                current=nxt,
                steps_left=steps_left - 1,
                current_path=current_path + [nxt],
                captures_so_far=new_captures,
                live_opp=new_live_opp,
                own_pieces=own_pieces,
                just_captured=is_capture,
                results=results,
            )

        # ── Forced stop: completely blocked ──────────────────────────────────
        # If we haven't moved at all AND we have a path (we're mid-move),
        # then the stone is stuck — record whatever we have as a valid
        # (forced) terminal position, even with steps remaining.
        if not moved_anywhere and current_path:
            results.append(Move(
                origin=origin,
                path=list(current_path),
                captures=list(captures_so_far),
            ))

    # ── Move application ──────────────────────────────────────────────────────

    def apply_move(self, move: Move) -> None:
        """Apply *move* to the game state (modifies in place)."""
        player = self.current_player
        opp    = self.opponent(player)

        # Move the piece
        self.pieces[player].discard(move.origin)
        self.pieces[player].add(move.destination)

        # Remove captured pieces
        for cap in move.captures:
            self.pieces[opp].discard(cap)

        # Record history
        self.history.append((player, move))
        self.last_move = move
        self.move_count += 1

        # Check win/draw conditions
        self._check_end_conditions()

        # Switch player
        if not self.game_over:
            self.current_player = self.opponent(player)

    def _check_end_conditions(self) -> None:
        opp = self.opponent(self.current_player)

        # Win condition 1: opponent has no pieces
        if self.piece_count(opp) == 0:
            self.winner = self.current_player
            self.game_over = True
            return

        # Win condition 2: opponent has exactly 1 piece AND current player
        #                   still has all 6 original pieces
        if self.piece_count(opp) == 1 and self.piece_count(self.current_player) == 6:
            self.winner = self.current_player
            self.game_over = True
            return

        # Draw: move limit reached
        if self.move_count >= DRAW_MOVE_LIMIT:
            self.winner = 0
            self.game_over = True
            return

        # No legal moves for next player (completely blocked)
        next_player = self.opponent(self.current_player)
        if not self.legal_moves(next_player):
            self.winner = self.current_player
            self.game_over = True

    # ── Validation helper ─────────────────────────────────────────────────────

    def is_legal_move(self, move: Move) -> bool:
        """Return True if *move* appears in the list of legal moves."""
        legal = self.legal_moves()
        for lm in legal:
            if lm.origin == move.origin and lm.path == move.path:
                return True
        return False

    # ── Snapshot / copy ───────────────────────────────────────────────────────

    def clone(self) -> "AnnuvinGame":
        """Return a deep copy of this game state (useful for AI search)."""
        new = AnnuvinGame.__new__(AnnuvinGame)
        new.board = self.board
        new.pieces = {k: set(v) for k, v in self.pieces.items()}
        new.current_player = self.current_player
        new.move_count = self.move_count
        new.history = list(self.history)
        new.winner = self.winner
        new.game_over = self.game_over
        new.last_move = self.last_move
        return new

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_text(self) -> str:
        p1 = " ".join(f"{q},{r},{s}" for q, r, s in sorted(self.pieces[1]))
        p2 = " ".join(f"{q},{r},{s}" for q, r, s in sorted(self.pieces[2]))
        return (
            f"MOVE {self.move_count}\n"
            f"PLAYER {self.current_player}\n"
            f"P1 {p1}\n"
            f"P2 {p2}\n"
        )

    @classmethod
    def from_text(cls, text: str) -> "AnnuvinGame":
        game = cls.__new__(cls)
        game.board = HexBoard(size=4)
        game.history = []
        game.winner = None
        game.game_over = False
        game.last_move = None

        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        if len(lines) < 4:
            raise ValueError("Incomplete save data.")

        def parse_pieces(line: str, prefix: str) -> Set[Cube]:
            tokens = line[len(prefix):].strip().split()
            result: Set[Cube] = set()
            for tok in tokens:
                parts = tok.split(",")
                if len(parts) != 3:
                    raise ValueError(f"Bad cube token: {tok!r}")
                q, r, s = int(parts[0]), int(parts[1]), int(parts[2])
                if q + r + s != 0:
                    raise ValueError(f"Invalid cube coord: {tok!r}")
                result.add((q, r, s))
            return result

        for line in lines:
            if line.startswith("MOVE "):
                game.move_count = int(line.split()[1])
            elif line.startswith("PLAYER "):
                game.current_player = int(line.split()[1])
            elif line.startswith("P1 "):
                game.pieces = {1: parse_pieces(line, "P1 "), 2: set()}
            elif line.startswith("P2 "):
                game.pieces[2] = parse_pieces(line, "P2 ")

        return game

    def history_to_text(self) -> str:
        lines = ["Annuvin — Game History", "=" * 40]
        for i, (player, move) in enumerate(self.history, 1):
            caps = ", ".join(str(c) for c in move.captures) or "none"
            lines.append(
                f"Move {i:3d} | Player {player} | "
                f"{move.origin} → {move.destination} | "
                f"captures: {caps}"
            )
        if self.game_over:
            if self.winner == 0:
                lines.append("\nResult: Draw (move limit reached)")
            else:
                lines.append(f"\nResult: Player {self.winner} wins!")
        return "\n".join(lines)


# ─── AI ────────────────────────────────────────────────────────────

# The AI module will be implemented in a later phase of the project.
# The stubs below define the interface so that the rest of the code can
# reference them without breaking.

class AnnuvinAI:
    """Base class for computer players."""

    def __init__(self, player: int, skill: str = "medium",
                 logger: Optional[AILogger] = None) -> None:
        self.player = player
        self.skill  = skill   # "easy" | "medium" | "hard"
        self.logger = logger

    def _log(self, message: str) -> None:
        if self.logger is not None:
            self.logger.log(message)

    def choose_move(self, game: AnnuvinGame) -> Move:
        raise NotImplementedError

class MinimaxAI(AnnuvinAI):
    """
    Minimax with alpha-beta pruning.

    Parameters
    ----------
    depth : int
        Search depth (higher = stronger but slower).
        easy   → depth 1
        medium → depth 2
        hard   → depth 3
    """

    SKILL_PROFILES = {
        "easy": {
            "depth": 1,
            "root_limit": 12,
            "branch_limit": 6,
            "time_limit": 0.15,
            "capture_bonus": 30.0,
            "material": 90.0,
            "speed": 20.0,
            "alternate": 300.0,
            "threat_penalty": 70.0,
            "threat_reward": 10.0,
            "mobility": 4.0,
            "centrality": 2.0,
            "proximity": 0.0,
        },
        "medium": {
            "depth": 2,
            "root_limit": 32,
            "branch_limit": 18,
            "time_limit": 0.90,
            "capture_bonus": 150.0,
            "material": 160.0,
            "speed": 45.0,
            "alternate": 900.0,
            "threat_penalty": 80.0,
            "threat_reward": 50.0,
            "mobility": 8.0,
            "centrality": 4.0,
            "proximity": -2.0,
        },
        "hard": {
            "depth": 3,
            "root_limit": 96,
            "branch_limit": 52,
            "time_limit": 2.50,
            "capture_bonus": 320.0,
            "material": 250.0,
            "speed": 40.0,
            "alternate": 1600.0,
            "threat_penalty": 95.0,
            "threat_reward": 95.0,
            "mobility": 6.0,
            "centrality": 3.0,
            "proximity": -6.0,
        },
    }

    def __init__(self, player: int, skill: str = "easy",
                 logger: Optional[AILogger] = None) -> None:
        super().__init__(player, skill, logger=logger)
        self.profile = self.SKILL_PROFILES.get(skill, self.SKILL_PROFILES["easy"])
        self.depth = self.profile["depth"]

    def _move_order_key(self, game: AnnuvinGame, move: Move) -> Tuple[int, int, int, int]:
        current_player = game.current_player
        enemy_player = self.player if current_player != self.player else game.opponent(self.player)
        enemy_pieces = game.pieces[enemy_player]

        if enemy_pieces:
            nearest_enemy = min(game.board.distance(move.destination, piece) for piece in enemy_pieces)
        else:
            nearest_enemy = 0

        nearest_enemy_origin = nearest_enemy
        if enemy_pieces:
            nearest_enemy_origin = min(game.board.distance(move.origin, piece) for piece in enemy_pieces)

        distance_delta = nearest_enemy_origin - nearest_enemy
        aggression = distance_delta
        if current_player == self.player:
            aggression += len(move.captures) * 2

        return (
            -len(move.captures),
            -aggression,
            nearest_enemy,
            game.board.distance(move.destination, (0, 0, 0)),
        )

    def _ordered_moves(self, game: AnnuvinGame, moves: List[Move], limit: int) -> List[Move]:
        ordered = sorted(moves, key=lambda move: self._move_order_key(game, move))
        return ordered[:limit]

    def _capture_bonus(self, game: AnnuvinGame, move: Move) -> float:
        bonus = self.profile["capture_bonus"] * len(move.captures)
        if not move.captures and self.skill in ("medium", "hard"):
            enemy_player = game.opponent(self.player)
            enemy_pieces = game.pieces[enemy_player]
            if enemy_pieces:
                origin_distance = min(game.board.distance(move.origin, piece) for piece in enemy_pieces)
                destination_distance = min(game.board.distance(move.destination, piece) for piece in enemy_pieces)
                bonus += max(0, origin_distance - destination_distance) * (10 if self.skill == "medium" else 18)
        return bonus

    def choose_move(self, game: AnnuvinGame) -> Move:
        deadline = time.perf_counter() + self.profile["time_limit"]
        opp = game.opponent(self.player)
        self._log(
            f"Turn start for player {self.player}: skill={self.skill}, depth={self.depth}, "
            f"pieces={game.piece_count(self.player)}, opponent_pieces={game.piece_count(opp)}, "
            f"steps={game.steps_for(self.player)}, time_limit={self.profile['time_limit']:.2f}s"
        )

        legal_moves = self._ordered_moves(
            game,
            game.legal_moves(self.player, max_moves=self.profile["root_limit"]),
            self.profile["root_limit"],
        )
        self._log(f"Root search space: {len(legal_moves)} legal move(s)")

        if not legal_moves:
            self._log("No legal moves available; raising error.")
            raise RuntimeError("MinimaxAI.choose_move called with no legal moves")

        best_move = legal_moves[0]
        best_score = float("-inf")
        scored_options: List[Tuple[float, Move]] = []
        alpha, beta = float("-inf"), float("inf")
        for index, move in enumerate(legal_moves, 1):
            if time.perf_counter() >= deadline:
                self._log(f"Search time budget exhausted after {index - 1} option(s).")
                break
            child = game.clone()
            child.apply_move(move)
            static_score, breakdown = self._evaluate_with_breakdown(child)
            score = self._minimax(child, self.depth - 1, alpha, beta, False, deadline)
            score += self._capture_bonus(game, move)
            scored_options.append((score, move))
            self._log(
                f"Option {index}: {move.origin} -> {move.destination}, caps={len(move.captures)}, "
                f"static={static_score:.1f}, search={score:.1f}, "
                f"material={breakdown['material']:.1f}, speed={breakdown['speed']:.1f}, "
                f"threat={breakdown['threat']:.1f}, mobility={breakdown['mobility']:.1f}, "
                f"center={breakdown['centrality']:.1f}, proximity={breakdown['proximity']:.1f}"
            )
            if score > best_score:
                best_score = score
                best_move = move
            alpha = max(alpha, best_score)

        if best_score == float("-inf"):
            best_score = self._capture_bonus(game, best_move)

        if scored_options:
            ranked = sorted(scored_options, key=lambda item: item[0], reverse=True)
            if self.skill == "easy":
                # Easy intentionally avoids always picking the best line.
                lower = 1 if len(ranked) > 1 else 0
                upper = min(len(ranked), 5)
                pool = ranked[lower:upper] or ranked
                best_score, best_move = random.choice(pool)
                self._log("Easy mode selected a non-optimal candidate from the top pool.")
            elif self.skill == "hard":
                # Hard always takes the strongest evaluated option.
                best_score, best_move = ranked[0]

        if not any(move.captures for move in legal_moves):
            self._log("No immediate capture was available; selecting the most aggressive legal move.")

        self._log(
            f"Chosen move: {best_move.origin} -> {best_move.destination}, caps={len(best_move.captures)}, "
            f"score={best_score:.1f}"
        )
        return best_move

    def _minimax(self, game: AnnuvinGame, depth: int,
                 alpha: float, beta: float, maximising: bool,
                 deadline: Optional[float] = None) -> float:
        if deadline is not None and time.perf_counter() >= deadline:
            return self._evaluate(game)
        if game.game_over or depth == 0:
            return self._evaluate(game)
        moves = self._ordered_moves(
            game,
            game.legal_moves(max_moves=self.profile["branch_limit"]),
            self.profile["branch_limit"],
        )
        if maximising:
            value = float("-inf")
            for move in moves:
                if deadline is not None and time.perf_counter() >= deadline:
                    break
                child = game.clone()
                child.apply_move(move)
                value = max(value, self._minimax(child, depth-1, alpha, beta, False, deadline))
                alpha = max(alpha, value)
                if beta <= alpha:
                    break  # β cut-off
            return value
        else:
            value = float("inf")
            for move in moves:
                if deadline is not None and time.perf_counter() >= deadline:
                    break
                child = game.clone()
                child.apply_move(move)
                value = min(value, self._minimax(child, depth-1, alpha, beta, True, deadline))
                beta = min(beta, value)
                if beta <= alpha:
                    break  # α cut-off
            return value

    def _evaluate(self, game: AnnuvinGame) -> float:
        """
        Heuristic evaluation function.
        Positive values favour self.player, negative favour opponent.
        """
        score, _ = self._evaluate_with_breakdown(game)
        return score

    def _evaluate_with_breakdown(self, game: AnnuvinGame) -> Tuple[float, Dict[str, float]]:
        """Return the heuristic score plus a component breakdown for logging."""
        opp = 2 if self.player == 1 else 1

        breakdown: Dict[str, float] = {
            "material": 0.0,
            "speed": 0.0,
            "alternate": 0.0,
            "threat": 0.0,
            "mobility": 0.0,
            "centrality": 0.0,
            "proximity": 0.0,
        }

        # ── Terminal states ───────────────────────────────────────────────────
        if game.winner == self.player:
            score = 10_000.0
            breakdown["terminal"] = score
            return score, breakdown
        if game.winner == opp:
            score = -10_000.0
            breakdown["terminal"] = score
            return score, breakdown
        if game.winner == 0:
            score = 0.0
            breakdown["terminal"] = score
            return score, breakdown

        own_count = game.piece_count(self.player)
        opp_count = game.piece_count(opp)
        own_steps = game.steps_for(self.player)
        opp_steps = game.steps_for(opp)

        score = 0.0

        # ── Material (dampened) ───────────────────────────────────────────────
        # Raw piece delta matters, but losing pieces gives steps — so the
        # advantage of being ahead in pieces is less than it first appears.
        breakdown["material"] = self.profile["material"] * (own_count - opp_count)
        score += breakdown["material"]

        # ── Speed advantage ───────────────────────────────────────────────────
        # Being the faster mover is independently valuable: more steps = more
        # capture opportunities and harder to block.
        breakdown["speed"] = self.profile["speed"] * (own_steps - opp_steps)
        score += breakdown["speed"]

        # ── Alternate win proximity ───────────────────────────────────────────
        # Win condition 2: you have all 6, opponent has exactly 1.
        # Give a strong bonus when one capture away from that state.
        if own_count == 6 and opp_count == 2:
            breakdown["alternate"] += self.profile["alternate"]
        if own_count == 6 and opp_count == 1:
            # Should be caught by winner check, but safety net:
            breakdown["alternate"] += 9_000
        score += breakdown["alternate"]

        # ── Threat & safety ───────────────────────────────────────────────────
        # A piece is "threatened" if any enemy can reach it within their
        # current step budget via BFS (ignoring own-piece blocking for speed).
        # A piece is "threatening" if it can reach any enemy within our budget.
        def reachable_cells(from_cells, steps, own_set, opp_set):
            """BFS: all cells reachable in `steps` hops from any cell in from_cells,
            ignoring friendly-piece blocking (conservative / fast approximation)."""
            from collections import deque
            visited = set(from_cells)
            frontier = deque((c, steps) for c in from_cells)
            result = set()
            while frontier:
                cell, remaining = frontier.popleft()
                if remaining == 0:
                    continue
                for d in CUBE_DIRECTIONS:
                    nxt = (cell[0]+d[0], cell[1]+d[1], cell[2]+d[2])
                    if not game.board.is_valid(nxt):
                        continue
                    result.add(nxt)
                    if nxt not in visited:
                        visited.add(nxt)
                        frontier.append((nxt, remaining - 1))
            return result

        opp_reach = reachable_cells(
            game.pieces[opp], opp_steps,
            game.pieces[opp], game.pieces[self.player]
        )
        own_reach = reachable_cells(
            game.pieces[self.player], own_steps,
            game.pieces[self.player], game.pieces[opp]
        )

        for piece in game.pieces[self.player]:
            if piece in opp_reach:
                breakdown["threat"] -= self.profile["threat_penalty"]   # this piece is in danger

        for piece in game.pieces[opp]:
            if piece in own_reach:
                breakdown["threat"] += self.profile["threat_reward"]   # we are threatening this enemy piece
        score += breakdown["threat"]

        # ── Mobility ──────────────────────────────────────────────────────────
        # Count valid one-step neighbours for all own pieces.
        # Penalises being cornered or hemmed in by own pieces.
        own_set = game.pieces[self.player]
        opp_set = game.pieces[opp]
        all_pieces = own_set | opp_set

        mobility = 0
        for piece in own_set:
            for d in CUBE_DIRECTIONS:
                nxt = (piece[0]+d[0], piece[1]+d[1], piece[2]+d[2])
                if game.board.is_valid(nxt) and nxt not in own_set:
                    mobility += 1
        breakdown["mobility"] = self.profile["mobility"] * mobility
        score += breakdown["mobility"]

        # ── Centrality ────────────────────────────────────────────────────────
        # Central pieces have 6 neighbours; edge/corner pieces have fewer
        # routes. Reward staying toward the center.
        origin = (0, 0, 0)
        max_dist = game.board.size - 1   # = 3 for HexHex-4
        for piece in own_set:
            dist_from_center = game.board.distance(piece, origin)
            breakdown["centrality"] += self.profile["centrality"] * (max_dist - dist_from_center)
        score += breakdown["centrality"]

        # ── Proximity ─────────────────────────────────────────────────────────
        # Light pull toward enemies: keeps the AI aggressive without
        # letting proximity dominate over material/threat signals.
        if opp_set:
            for piece in own_set:
                min_dist = min(game.board.distance(piece, e) for e in opp_set)
                breakdown["proximity"] += self.profile["proximity"] * min_dist
        score += breakdown["proximity"]

        return score, breakdown
