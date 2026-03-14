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
steps (it may also "pass through" cells occupied by own pieces, but cannot
*end* a step on them or on empty cells after the allowance is exhausted).

Captures:
  • Moving onto a cell occupied by an opponent captures that piece.
  • After a capture the moving stone may continue spending its remaining steps,
    and may make further captures.
  • A stone CANNOT move through a captured piece's position AFTER the capture
    (the cell is now empty, so it is fine to traverse).
  • A stone CAN stop on an enemy cell (capture) before spending all steps — the
    remaining steps are simply forfeited.
  • A stone CANNOT voluntarily stop mid-move on an empty cell (you must use all
    remaining steps OR stop on a capture).

Special rule — mandatory use of all steps:
  The player MUST move a stone using ALL of its allotted steps, unless the only
  way to move would be to capture one of their OWN pieces, in which case the
  stone stops early.

Win conditions:
  1. A player captures every opponent piece.
  2. A player reduces the opponent to exactly 1 stone while still having all 6
     of their own pieces intact.

Draw: Not explicitly defined in the original rules; we add a 150-move limit to
avoid infinite games (each player move counts as one move).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from annuvin.board import HexBoard, Cube, _cube_add, CUBE_DIRECTIONS

DRAW_MOVE_LIMIT = 150   # half-moves before automatic draw


# ─── Data transfer objects ────────────────────────────────────────────────────

@dataclass
class Move:
    """A complete move: a piece at *origin* following a sequence of *path* cells."""
    origin: Cube
    path: List[Cube]          # list of cells visited in order (length == steps)
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

    Attributes
    ----------
    board         : HexBoard  — immutable grid topology
    pieces        : dict[player_id → set of cube positions]
    current_player: 1 or 2
    move_count    : number of half-moves played so far
    history       : list of (player, Move) played
    winner        : None | 1 | 2 | 0 (0 = draw)
    game_over     : bool
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
        self.winner: Optional[int] = None   # None=ongoing, 0=draw, 1 or 2=winner
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

    def legal_moves(self, player: Optional[int] = None) -> List[Move]:
        """Return every legal move for *player* (defaults to current_player)."""
        if player is None:
            player = self.current_player
        steps = self.steps_for(player)
        moves: List[Move] = []
        for origin in list(self.pieces[player]):
            self._expand_paths(
                player, origin, origin, steps,
                current_path=[], captures_so_far=[],
                own_pieces=frozenset(self.pieces[player]),
                opp_pieces=frozenset(self.pieces[self.opponent(player)]),
                results=moves,
            )
        return moves

    def _expand_paths(
        self,
        player: int,
        origin: Cube,
        current: Cube,
        steps_left: int,
        current_path: List[Cube],
        captures_so_far: List[Cube],
        own_pieces: FrozenSet[Cube],
        opp_pieces: FrozenSet[Cube],
        results: List[Move],
    ) -> None:
        """
        Recursive DFS to build all valid paths for a stone starting at *origin*.

        A path is valid (and added to *results*) when:
          • All steps_left steps have been used (end of allowance), OR
          • The last step was a capture and there are remaining steps
            (the player may CHOOSE to stop after a capture).

        Stopping on an empty cell before exhausting steps is NOT allowed.
        """
        # Track which enemy pieces are still alive for this path
        # (pieces captured earlier in this path are gone from opp set)
        live_opp = frozenset(c for c in opp_pieces if c not in captures_so_far)
        live_opp_mutable = set(live_opp)  # needed for re-passing through captured spots

        if steps_left == 0:
            # Must end the move here — record if destination is valid
            # (cannot end on own piece; capture already handled when stepping in)
            if current not in own_pieces or current == origin:
                results.append(Move(
                    origin=origin,
                    path=list(current_path),
                    captures=list(captures_so_far),
                ))
            return

        # After a capture: player may CHOOSE to stop here (early termination)
        if captures_so_far and current_path:
            last = current_path[-1]
            if last in captures_so_far:
                # Stopping here is allowed (destination is the capture cell)
                results.append(Move(
                    origin=origin,
                    path=list(current_path),
                    captures=list(captures_so_far),
                ))
                # … but also continue exploring further steps (fall through)

        # Try all 6 neighbours
        for direction in CUBE_DIRECTIONS:
            nxt = _cube_add(current, direction)
            if not self.board.is_valid(nxt):
                continue

            if nxt in own_pieces and nxt != origin:
                # Cannot step onto (or through and stop on) own piece.
                # In Annuvin pieces may NOT pass through their own pieces;
                # the movement is blocked.
                continue

            new_captures = list(captures_so_far)
            new_opp = set(live_opp_mutable)

            if nxt in new_opp:
                # Capture: remove from live opponents for rest of this path
                new_captures.append(nxt)
                new_opp.discard(nxt)

            new_path = current_path + [nxt]
            self._expand_paths(
                player=player,
                origin=origin,
                current=nxt,
                steps_left=steps_left - 1,
                current_path=new_path,
                captures_so_far=new_captures,
                own_pieces=own_pieces,
                opp_pieces=frozenset(new_opp),
                results=results,
            )

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
            self.winner = 0   # draw
            self.game_over = True
            return

        # No legal moves for next player (shouldn't normally happen, but safeguard)
        next_player = self.opponent(self.current_player)
        if not self.legal_moves(next_player):
            # The player with no moves loses
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
        new.board = self.board             # board is immutable, safe to share
        new.pieces = {k: set(v) for k, v in self.pieces.items()}
        new.current_player = self.current_player
        new.move_count = self.move_count
        new.history = list(self.history)   # shallow copy of history tuples
        new.winner = self.winner
        new.game_over = self.game_over
        new.last_move = self.last_move
        return new

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_text(self) -> str:
        """
        Serialise the current board state to a human-readable text format.

        Format:
            MOVE <n>
            PLAYER <current>
            P1 <q1,r1,s1> <q2,r2,s2> ...
            P2 <q1,r1,s1> ...
        """
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
        """
        Load a game state from the text format produced by *to_text()*.
        Raises ValueError on malformed input.
        """
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

    # ── History export ────────────────────────────────────────────────────────

    def history_to_text(self) -> str:
        """Return a text log of all moves played so far."""
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


# ─── AI placeholder ────────────────────────────────────────────────────────────
#
# The AI module will be implemented in a later phase of the project.
# The stubs below define the interface so that the rest of the code can
# reference them without breaking.
#
# class AnnuvinAI:
#     """Base class for computer players."""
#
#     def __init__(self, player: int, skill: str = "medium") -> None:
#         self.player = player
#         self.skill  = skill   # "easy" | "medium" | "hard"
#
#     def choose_move(self, game: AnnuvinGame) -> Move:
#         raise NotImplementedError
#
#
# class MinimaxAI(AnnuvinAI):
#     """
#     Minimax with alpha-beta pruning.
#
#     Parameters
#     ----------
#     depth : int
#         Search depth (higher = stronger but slower).
#         easy   → depth 1
#         medium → depth 3
#         hard   → depth 5
#     """
#
#     DEPTH_MAP = {"easy": 1, "medium": 3, "hard": 5}
#
#     def __init__(self, player: int, skill: str = "medium") -> None:
#         super().__init__(player, skill)
#         self.depth = self.DEPTH_MAP.get(skill, 3)
#
#     def choose_move(self, game: AnnuvinGame) -> Move:
#         best_move = None
#         best_score = float("-inf")
#         alpha, beta = float("-inf"), float("inf")
#         for move in game.legal_moves(self.player):
#             child = game.clone()
#             child.apply_move(move)
#             score = self._minimax(child, self.depth - 1, alpha, beta, False)
#             if score > best_score:
#                 best_score = score
#                 best_move = move
#             alpha = max(alpha, best_score)
#         return best_move
#
#     def _minimax(self, game: AnnuvinGame, depth: int,
#                  alpha: float, beta: float, maximising: bool) -> float:
#         if game.game_over or depth == 0:
#             return self._evaluate(game)
#         moves = game.legal_moves()
#         if maximising:
#             value = float("-inf")
#             for move in moves:
#                 child = game.clone()
#                 child.apply_move(move)
#                 value = max(value, self._minimax(child, depth-1, alpha, beta, False))
#                 alpha = max(alpha, value)
#                 if beta <= alpha:
#                     break  # β cut-off
#             return value
#         else:
#             value = float("inf")
#             for move in moves:
#                 child = game.clone()
#                 child.apply_move(move)
#                 value = min(value, self._minimax(child, depth-1, alpha, beta, True))
#                 beta = min(beta, value)
#                 if beta <= alpha:
#                     break  # α cut-off
#             return value
#
#     def _evaluate(self, game: AnnuvinGame) -> float:
#         """
#         Heuristic evaluation function.
#         Positive values favour self.player, negative favour opponent.
#         """
#         opp = 2 if self.player == 1 else 1
#         if game.winner == self.player:
#             return 10_000.0
#         if game.winner == opp:
#             return -10_000.0
#         if game.winner == 0:
#             return 0.0
#         # Material score: each of our pieces = +10, each opponent piece = -10
#         score  =  10 * game.piece_count(self.player)
#         score -= 10 * game.piece_count(opp)
#         # Mobility score: more moves available = better
#         score += 0.5 * len(game.legal_moves(self.player))
#         score -= 0.5 * len(game.legal_moves(opp))
#         return score
#
#
# class MCTSNode:
#     """Node in the Monte Carlo Tree Search tree."""
#
#     def __init__(self, game: AnnuvinGame, parent: Optional["MCTSNode"] = None,
#                  move: Optional[Move] = None) -> None:
#         self.game     = game
#         self.parent   = parent
#         self.move     = move
#         self.children: List["MCTSNode"] = []
#         self.wins     = 0.0
#         self.visits   = 0
#         self.untried_moves: List[Move] = game.legal_moves()
#
#     @property
#     def ucb1(self) -> float:
#         import math
#         if self.visits == 0:
#             return float("inf")
#         return (self.wins / self.visits +
#                 1.41 * math.sqrt(math.log(self.parent.visits) / self.visits))
#
#
# class MCTSAI(AnnuvinAI):
#     """
#     Monte Carlo Tree Search player.
#
#     Parameters
#     ----------
#     iterations : int
#         Number of simulation iterations per move.
#         easy   → 200
#         medium → 1000
#         hard   → 5000
#     """
#
#     ITER_MAP = {"easy": 200, "medium": 1000, "hard": 5000}
#
#     def __init__(self, player: int, skill: str = "medium") -> None:
#         super().__init__(player, skill)
#         self.iterations = self.ITER_MAP.get(skill, 1000)
#
#     def choose_move(self, game: AnnuvinGame) -> Move:
#         import random
#         root = MCTSNode(game.clone())
#         for _ in range(self.iterations):
#             node = self._select(root)
#             result = self._simulate(node.game.clone())
#             self._backpropagate(node, result)
#         best = max(root.children, key=lambda n: n.visits)
#         return best.move
#
#     def _select(self, node: "MCTSNode") -> "MCTSNode":
#         while not node.game.game_over:
#             if node.untried_moves:
#                 return self._expand(node)
#             node = max(node.children, key=lambda n: n.ucb1)
#         return node
#
#     def _expand(self, node: "MCTSNode") -> "MCTSNode":
#         import random
#         move = node.untried_moves.pop(random.randrange(len(node.untried_moves)))
#         child_game = node.game.clone()
#         child_game.apply_move(move)
#         child = MCTSNode(child_game, parent=node, move=move)
#         node.children.append(child)
#         return child
#
#     def _simulate(self, game: AnnuvinGame) -> int:
#         """Random rollout; returns winner (0=draw, 1 or 2)."""
#         import random
#         while not game.game_over:
#             moves = game.legal_moves()
#             if not moves:
#                 break
#             game.apply_move(random.choice(moves))
#         return game.winner or 0
#
#     def _backpropagate(self, node: "MCTSNode", result: int) -> None:
#         while node is not None:
#             node.visits += 1
#             if result == self.player:
#                 node.wins += 1.0
#             elif result == 0:
#                 node.wins += 0.5
#             node = node.parent
