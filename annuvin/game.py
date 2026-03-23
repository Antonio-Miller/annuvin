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
import sys
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from annuvin.board import HexBoard, Cube, _cube_add, CUBE_DIRECTIONS

DRAW_MOVE_LIMIT = 150   # half-moves before automatic draw

sys.setrecursionlimit(10000)

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
        adjusted_max = max(30, max_moves // steps)
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

    def __init__(self, player: int, skill: str = "medium") -> None:
        self.player = player
        self.skill  = skill   # "easy" | "medium" | "hard"

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

    DEPTH_MAP = {"easy": 1, "medium": 2, "hard": 3}

    def __init__(self, player: int, skill: str = "easy") -> None:
        super().__init__(player, skill)
        self.depth = self.DEPTH_MAP.get(skill, 1)

    def choose_move(self, game: AnnuvinGame) -> Move:
        best_move = None
        best_score = float("-inf")
        alpha, beta = float("-inf"), float("inf")
        for move in game.legal_moves(self.player):
            child = game.clone()
            child.apply_move(move)
            score = self._minimax(child, self.depth - 1, alpha, beta, False)
            if score > best_score:
                best_score = score
                best_move = move
            alpha = max(alpha, best_score)
        return best_move

    def _minimax(self, game: AnnuvinGame, depth: int,
                 alpha: float, beta: float, maximising: bool) -> float:
        if game.game_over or depth == 0:
            return self._evaluate(game)
        moves = game.legal_moves()
        if maximising:
            value = float("-inf")
            for move in moves:
                child = game.clone()
                child.apply_move(move)
                value = max(value, self._minimax(child, depth-1, alpha, beta, False))
                alpha = max(alpha, value)
                if beta <= alpha:
                    break  # β cut-off
            return value
        else:
            value = float("inf")
            for move in moves:
                child = game.clone()
                child.apply_move(move)
                value = min(value, self._minimax(child, depth-1, alpha, beta, True))
                beta = min(beta, value)
                if beta <= alpha:
                    break  # α cut-off
            return value

    def _evaluate(self, game: AnnuvinGame) -> float:
        """
        Heuristic evaluation function.
        Positive values favour self.player, negative favour opponent.
        """
        opp = 2 if self.player == 1 else 1
        if game.winner == self.player:
            return 10_000.0
        if game.winner == opp:
            return -10_000.0
        if game.winner == 0:
            return 0.0
        
        own_count = game.piece_count(self.player)
        opp_count = game.piece_count(opp)

        # Material — the only thing that really matters
        score = 200 * (own_count - opp_count)

        # Proximity — reward being close to enemy pieces
        for own in game.pieces[self.player]:
            if game.pieces[opp]:
                min_dist = min(game.board.distance(own, e) for e in game.pieces[opp])
                score -= 5 * min_dist

        return score


class MCTSNode:
    """Node in the Monte Carlo Tree Search tree."""

    def __init__(self, game: AnnuvinGame, parent: Optional["MCTSNode"] = None,
                 move: Optional[Move] = None) -> None:
        self.game     = game
        self.parent   = parent
        self.move     = move
        self.children: List["MCTSNode"] = []
        self.wins     = 0.0
        self.visits   = 0
        self.untried_moves: List[Move] = game.legal_moves()

    @property
    def ucb1(self) -> float:
        import math
        if self.visits == 0:
            return float("inf")
        return (self.wins / self.visits +
                1.41 * math.sqrt(math.log(self.parent.visits) / self.visits))

class MCTSAI(AnnuvinAI):
    """
    Monte Carlo Tree Search player.

    Parameters
    ----------
    iterations : int
        Number of simulation iterations per move.
        easy   → 200
        medium → 1000
        hard   → 5000
    """

    ITER_MAP = {"easy": 200, "medium": 1000, "hard": 5000}

    def __init__(self, player: int, skill: str = "medium") -> None:
        super().__init__(player, skill)
        self.iterations = self.ITER_MAP.get(skill, 1000)

    def choose_move(self, game: AnnuvinGame) -> Move:
        import random
        root = MCTSNode(game.clone())
        for _ in range(self.iterations):
            node = self._select(root)
            result = self._simulate(node.game.clone())
            self._backpropagate(node, result)
        best = max(root.children, key=lambda n: n.visits)
        return best.move

    def _select(self, node: "MCTSNode") -> "MCTSNode":
        while not node.game.game_over:
            if node.untried_moves:
                return self._expand(node)
            node = max(node.children, key=lambda n: n.ucb1)
        return node

    def _expand(self, node: "MCTSNode") -> "MCTSNode":
        import random
        move = node.untried_moves.pop(random.randrange(len(node.untried_moves)))
        child_game = node.game.clone()
        child_game.apply_move(move)
        child = MCTSNode(child_game, parent=node, move=move)
        node.children.append(child)
        return child

    def _simulate(self, game: AnnuvinGame) -> int:
        """Random rollout; returns winner (0=draw, 1 or 2)."""
        import random
        while not game.game_over:
            moves = game.legal_moves()
            if not moves:
                break
            game.apply_move(random.choice(moves))
        return game.winner or 0

    def _backpropagate(self, node: "MCTSNode", result: int) -> None:
        while node is not None:
            node.visits += 1
            if result == self.player:
                node.wins += 1.0
            elif result == 0:
                node.wins += 0.5
            node = node.parent
