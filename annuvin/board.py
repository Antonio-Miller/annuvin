"""
board.py — Hexagonal grid model for Annuvin.

Uses cube coordinates (q, r, s) where q + r + s == 0.
The board is a HexHex-4 (hexagonal board with 4 hexes on each side),
giving a total of 37 cells.

Cube-coordinate neighbours use the six axial directions:
  (+1,-1,0), (+1,0,-1), (0,+1,-1), (-1,+1,0), (-1,0,+1), (0,-1,+1)

Flat-top hex pixel conversion (used by renderer):
  x = hex_size * (3/2 * q)
  y = hex_size * (sqrt(3)/2 * q  +  sqrt(3) * r)
"""

from __future__ import annotations
import math
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

# Six axial directions for cube coordinates
CUBE_DIRECTIONS: List[Tuple[int, int, int]] = [
    ( 1, -1,  0),
    ( 1,  0, -1),
    ( 0,  1, -1),
    (-1,  1,  0),
    (-1,  0,  1),
    ( 0, -1,  1),
]

Cube = Tuple[int, int, int]


def _cube_add(a: Cube, b: Cube) -> Cube:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _cube_distance(a: Cube, b: Cube) -> int:
    return (abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])) // 2


def _cube_neighbours(cell: Cube) -> List[Cube]:
    return [_cube_add(cell, d) for d in CUBE_DIRECTIONS]


def _generate_hexhex(size: int) -> FrozenSet[Cube]:
    """Return all cube coordinates for a HexHex board of the given side length."""
    cells: Set[Cube] = set()
    n = size - 1
    for q in range(-n, n + 1):
        for r in range(-n, n + 1):
            s = -q - r
            if abs(s) <= n:
                cells.add((q, r, s))
    return frozenset(cells)


class HexBoard:
    """
    Immutable hexagonal grid topology.

    Holds the set of valid cells and exposes adjacency / geometry helpers.
    Does NOT store piece positions — that is the responsibility of GameState.
    """

    def __init__(self, size: int = 4) -> None:
        self.size = size
        self.cells: FrozenSet[Cube] = _generate_hexhex(size)

    # ── Topology ──────────────────────────────────────────────────────────────

    def neighbours(self, cell: Cube) -> List[Cube]:
        """Return the on-board neighbours of *cell*."""
        return [n for n in _cube_neighbours(cell) if n in self.cells]

    def is_valid(self, cell: Cube) -> bool:
        return cell in self.cells

    def distance(self, a: Cube, b: Cube) -> int:
        return _cube_distance(a, b)

    # ── Geometry (pixel positions, flat-top orientation) ──────────────────────

    def cube_to_pixel(self, cell: Cube, hex_radius: float,
                      origin_x: float, origin_y: float) -> Tuple[float, float]:
        """Convert cube coords to pixel centre (flat-top hexagons)."""
        q, r, _ = cell
        x = hex_radius * (3 / 2 * q)
        y = hex_radius * (math.sqrt(3) / 2 * q + math.sqrt(3) * r)
        return origin_x + x, origin_y + y

    def pixel_to_cube(self, px: float, py: float, hex_radius: float,
                      origin_x: float, origin_y: float) -> Optional[Cube]:
        """Convert pixel position to the nearest valid cube coordinate."""
        x = px - origin_x
        y = py - origin_y
        q = (2 / 3 * x) / hex_radius
        r = (-1 / 3 * x + math.sqrt(3) / 3 * y) / hex_radius
        s = -q - r
        cube = _cube_round(q, r, s)
        return cube if cube in self.cells else None

    # ── Initial piece placement ───────────────────────────────────────────────

    def initial_positions(self) -> Dict[int, List[Cube]]:
        """
        Return the starting positions for both players on a HexHex-4 board.

        Player 1 occupies one corner cluster; Player 2 occupies the opposite.
        Each player starts with 6 pieces arranged in the corner region
        (the cell at maximum negative q + r + s corner and its 5 nearest neighbours
        within the board).
        """
        n = self.size - 1  # == 3 for standard board

        # Corner cells for player 1: top-left corner cluster
        # In cube coordinates the "top-left" corner anchor is (-n, n, 0) area.
        # We pick the 6 cells closest to the corner (-n, 0, n).
        p1_anchor: Cube = (-n, 0, n)
        p2_anchor: Cube = (n, 0, -n)

        p1_cells = self._corner_cluster(p1_anchor, 6)
        p2_cells = self._corner_cluster(p2_anchor, 6)

        return {1: p1_cells, 2: p2_cells}

    def _corner_cluster(self, anchor: Cube, count: int) -> List[Cube]:
        """BFS from *anchor* to collect *count* cells (anchor first)."""
        visited: List[Cube] = []
        queue = [anchor]
        seen: Set[Cube] = {anchor}
        while queue and len(visited) < count:
            cell = queue.pop(0)
            visited.append(cell)
            for nb in sorted(self.neighbours(cell),
                             key=lambda c: _cube_distance(c, anchor)):
                if nb not in seen:
                    seen.add(nb)
                    queue.append(nb)
        return visited[:count]

    def all_cells_sorted(self) -> List[Cube]:
        """Return all cells sorted for deterministic iteration."""
        return sorted(self.cells)


# ── Cube rounding ─────────────────────────────────────────────────────────────

def _cube_round(fq: float, fr: float, fs: float) -> Cube:
    q, r, s = round(fq), round(fr), round(fs)
    dq, dr, ds = abs(q - fq), abs(r - fr), abs(s - fs)
    if dq > dr and dq > ds:
        q = -r - s
    elif dr > ds:
        r = -q - s
    else:
        s = -q - r
    return (q, r, s)
