"""
benchmark.py — AI performance comparison for Annuvin.

Runs multiple headless games (no GUI) between AI players with different
difficulty levels, collects statistics and exports results to a text file.

Usage:
    python benchmark.py                      # run all matchups, 10 games each
    python benchmark.py --games 20           # 20 games per matchup
    python benchmark.py --matchups easy:hard  # only easy vs hard
    python benchmark.py --matchups easy:easy,medium:hard --games 5

Output:
    - Console table with results
    - results/benchmark_YYYYMMDD_HHMMSS.txt  with full details
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Tuple

# Ensure project root is in path
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from annuvin.game import AnnuvinGame, MinimaxAI, AILogger


# ─── Run a single headless game ─────────────────────────────────────────────

def run_game(p1_skill: str, p2_skill: str,
             logger: AILogger = None) -> Dict:
    """
    Run a single headless game between two MinimaxAI players.
    Returns a dict with all relevant stats.
    """
    game = AnnuvinGame()

    ai1 = MinimaxAI(player=1, skill=p1_skill, logger=logger)
    ai2 = MinimaxAI(player=2, skill=p2_skill, logger=logger)
    ais = {1: ai1, 2: ai2}

    stats = {
        1: {"move_times": [], "captures": 0},
        2: {"move_times": [], "captures": 0},
    }

    game_start = time.perf_counter()

    while not game.game_over:
        player = game.current_player
        ai = ais[player]
        snapshot = game.clone()

        t0 = time.perf_counter()
        move = ai.choose_move(snapshot)
        t1 = time.perf_counter()

        stats[player]["move_times"].append(t1 - t0)
        stats[player]["captures"] += len(move.captures)

        game.apply_move(move)

    game_end = time.perf_counter()

    # Count moves per player
    p1_moves = sum(1 for p, _ in game.history if p == 1)
    p2_moves = sum(1 for p, _ in game.history if p == 2)

    return {
        "winner": game.winner,              # 0=draw, 1 or 2
        "total_moves": game.move_count,
        "total_time": game_end - game_start,
        "p1_moves": p1_moves,
        "p2_moves": p2_moves,
        "p1_captures": stats[1]["captures"],
        "p2_captures": stats[2]["captures"],
        "p1_pieces_left": game.piece_count(1),
        "p2_pieces_left": game.piece_count(2),
        "p1_avg_time": sum(stats[1]["move_times"]) / len(stats[1]["move_times"]) if stats[1]["move_times"] else 0,
        "p2_avg_time": sum(stats[2]["move_times"]) / len(stats[2]["move_times"]) if stats[2]["move_times"] else 0,
        "p1_total_time": sum(stats[1]["move_times"]),
        "p2_total_time": sum(stats[2]["move_times"]),
    }


# ─── Run a full matchup (N games) ───────────────────────────────────────────

def run_matchup(p1_skill: str, p2_skill: str, num_games: int,
                logger: AILogger = None) -> Dict:
    """
    Run num_games between p1_skill and p2_skill.
    Returns aggregated statistics.
    """
    label = f"{p1_skill} vs {p2_skill}"
    print(f"\n{'='*60}")
    print(f"  Matchup: Player 1 ({p1_skill}) vs Player 2 ({p2_skill})")
    print(f"  Games: {num_games}")
    print(f"{'='*60}")

    results = []
    p1_wins = 0
    p2_wins = 0
    draws = 0

    for i in range(1, num_games + 1):
        print(f"  Game {i}/{num_games}...", end=" ", flush=True)
        t0 = time.perf_counter()
        result = run_game(p1_skill, p2_skill, logger=logger)
        elapsed = time.perf_counter() - t0
        results.append(result)

        if result["winner"] == 1:
            p1_wins += 1
            outcome = f"P1 wins"
        elif result["winner"] == 2:
            p2_wins += 1
            outcome = f"P2 wins"
        else:
            draws += 1
            outcome = "Draw"

        print(f"{outcome} in {result['total_moves']} moves ({elapsed:.1f}s)")

    # Aggregate stats
    total = len(results)
    avg_moves = sum(r["total_moves"] for r in results) / total
    avg_game_time = sum(r["total_time"] for r in results) / total
    avg_p1_time = sum(r["p1_avg_time"] for r in results) / total
    avg_p2_time = sum(r["p2_avg_time"] for r in results) / total
    avg_p1_captures = sum(r["p1_captures"] for r in results) / total
    avg_p2_captures = sum(r["p2_captures"] for r in results) / total

    # Average moves to win (only for games that had a winner)
    p1_win_moves = [r["total_moves"] for r in results if r["winner"] == 1]
    p2_win_moves = [r["total_moves"] for r in results if r["winner"] == 2]
    avg_p1_win_moves = sum(p1_win_moves) / len(p1_win_moves) if p1_win_moves else 0
    avg_p2_win_moves = sum(p2_win_moves) / len(p2_win_moves) if p2_win_moves else 0

    summary = {
        "p1_skill": p1_skill,
        "p2_skill": p2_skill,
        "num_games": total,
        "p1_wins": p1_wins,
        "p2_wins": p2_wins,
        "draws": draws,
        "p1_win_pct": (p1_wins / total) * 100,
        "p2_win_pct": (p2_wins / total) * 100,
        "draw_pct": (draws / total) * 100,
        "avg_moves": avg_moves,
        "avg_game_time": avg_game_time,
        "avg_p1_move_time": avg_p1_time,
        "avg_p2_move_time": avg_p2_time,
        "avg_p1_captures": avg_p1_captures,
        "avg_p2_captures": avg_p2_captures,
        "avg_p1_win_moves": avg_p1_win_moves,
        "avg_p2_win_moves": avg_p2_win_moves,
        "games": results,
    }

    # Print summary
    print(f"\n  Results: P1 wins {p1_wins} ({summary['p1_win_pct']:.0f}%) | "
          f"P2 wins {p2_wins} ({summary['p2_win_pct']:.0f}%) | "
          f"Draws {draws} ({summary['draw_pct']:.0f}%)")
    print(f"  Avg moves per game: {avg_moves:.1f}")
    print(f"  Avg time per move: P1={avg_p1_time:.3f}s  P2={avg_p2_time:.3f}s")

    return summary


# ─── Export results ──────────────────────────────────────────────────────────

def export_results(matchups: List[Dict], filepath: str) -> None:
    """Write all matchup results to a text file."""
    lines = []
    lines.append("=" * 70)
    lines.append("ANNUVIN — AI Performance Benchmark")
    lines.append("=" * 70)
    lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Total matchups: {len(matchups)}")
    lines.append("")

    # ── Summary table ────────────────────────────────────────────────────
    lines.append("-" * 70)
    lines.append(f"{'Matchup':<20} {'Games':>5} {'P1 W':>5} {'P2 W':>5} "
                 f"{'Draw':>5} {'P1%':>6} {'P2%':>6} {'Avg Mv':>7} "
                 f"{'P1 t/mv':>8} {'P2 t/mv':>8}")
    lines.append("-" * 70)

    for m in matchups:
        label = f"{m['p1_skill']} vs {m['p2_skill']}"
        lines.append(
            f"{label:<20} {m['num_games']:>5} {m['p1_wins']:>5} {m['p2_wins']:>5} "
            f"{m['draws']:>5} {m['p1_win_pct']:>5.0f}% {m['p2_win_pct']:>5.0f}% "
            f"{m['avg_moves']:>7.1f} {m['avg_p1_move_time']:>7.3f}s "
            f"{m['avg_p2_move_time']:>7.3f}s"
        )

    lines.append("-" * 70)
    lines.append("")

    # ── Detailed results per matchup ─────────────────────────────────────
    for m in matchups:
        lines.append("=" * 70)
        lines.append(f"Matchup: Player 1 ({m['p1_skill']}) vs Player 2 ({m['p2_skill']})")
        lines.append(f"Games played: {m['num_games']}")
        lines.append("")

        lines.append("Results:")
        lines.append(f"  Player 1 wins: {m['p1_wins']} ({m['p1_win_pct']:.1f}%)")
        lines.append(f"  Player 2 wins: {m['p2_wins']} ({m['p2_win_pct']:.1f}%)")
        lines.append(f"  Draws:         {m['draws']} ({m['draw_pct']:.1f}%)")
        lines.append("")

        lines.append("Performance:")
        lines.append(f"  Avg total moves per game:    {m['avg_moves']:.1f}")
        lines.append(f"  Avg moves to P1 win:         {m['avg_p1_win_moves']:.1f}" if m['avg_p1_win_moves'] else "  Avg moves to P1 win:         N/A")
        lines.append(f"  Avg moves to P2 win:         {m['avg_p2_win_moves']:.1f}" if m['avg_p2_win_moves'] else "  Avg moves to P2 win:         N/A")
        lines.append(f"  Avg time per move (P1):      {m['avg_p1_move_time']:.4f}s")
        lines.append(f"  Avg time per move (P2):      {m['avg_p2_move_time']:.4f}s")
        lines.append(f"  Avg captures per game (P1):  {m['avg_p1_captures']:.1f}")
        lines.append(f"  Avg captures per game (P2):  {m['avg_p2_captures']:.1f}")
        lines.append(f"  Avg game duration:           {m['avg_game_time']:.1f}s")
        lines.append("")

        # Per-game detail
        lines.append(f"  {'Game':<6} {'Winner':<8} {'Moves':>6} {'P1 cap':>7} "
                     f"{'P2 cap':>7} {'P1 t/mv':>8} {'P2 t/mv':>8} {'Time':>7}")
        lines.append(f"  {'-'*62}")
        for i, g in enumerate(m["games"], 1):
            w = "P1" if g["winner"] == 1 else ("P2" if g["winner"] == 2 else "Draw")
            lines.append(
                f"  {i:<6} {w:<8} {g['total_moves']:>6} {g['p1_captures']:>7} "
                f"{g['p2_captures']:>7} {g['p1_avg_time']:>7.3f}s "
                f"{g['p2_avg_time']:>7.3f}s {g['total_time']:>6.1f}s"
            )
        lines.append("")

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ─── Main ────────────────────────────────────────────────────────────────────

DEFAULT_MATCHUPS = [
    ("easy",   "easy"),
    ("easy",   "medium"),
    ("easy",   "hard"),
    ("medium", "medium"),
    ("medium", "hard"),
    ("hard",   "hard"),
]


def parse_matchups(s: str) -> List[Tuple[str, str]]:
    """Parse 'easy:hard,medium:hard' into [('easy','hard'), ('medium','hard')]."""
    result = []
    for pair in s.split(","):
        parts = pair.strip().split(":")
        if len(parts) != 2:
            print(f"Warning: ignoring invalid matchup '{pair}' (use format skill1:skill2)")
            continue
        p1, p2 = parts[0].strip(), parts[1].strip()
        if p1 not in ("easy", "medium", "hard") or p2 not in ("easy", "medium", "hard"):
            print(f"Warning: ignoring invalid skill in '{pair}' (use easy/medium/hard)")
            continue
        result.append((p1, p2))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Annuvin AI Performance Benchmark"
    )
    parser.add_argument(
        "--games", type=int, default=10,
        help="Number of games per matchup (default: 10)"
    )
    parser.add_argument(
        "--matchups", type=str, default=None,
        help="Comma-separated matchups, e.g. 'easy:hard,medium:hard' (default: all combinations)"
    )
    parser.add_argument(
        "--log", action="store_true",
        help="Enable AI thinking log (warning: very verbose)"
    )
    args = parser.parse_args()

    if args.matchups:
        matchups = parse_matchups(args.matchups)
        if not matchups:
            print("Error: no valid matchups specified.")
            sys.exit(1)
    else:
        matchups = DEFAULT_MATCHUPS

    logger = None
    if args.log:
        log_path = os.path.join(_HERE, "logs", "benchmark.log")
        logger = AILogger(log_path, clear=True)

    print("\n" + "=" * 60)
    print("  ANNUVIN — AI Performance Benchmark")
    print("=" * 60)
    print(f"  Games per matchup: {args.games}")
    print(f"  Matchups to run:   {len(matchups)}")
    for p1, p2 in matchups:
        print(f"    - {p1} vs {p2}")

    total_start = time.perf_counter()
    all_results = []

    for p1_skill, p2_skill in matchups:
        summary = run_matchup(p1_skill, p2_skill, args.games, logger=logger)
        all_results.append(summary)

    total_time = time.perf_counter() - total_start

    # Print final summary table
    print("\n\n" + "=" * 70)
    print("  FINAL SUMMARY")
    print("=" * 70)
    print(f"  {'Matchup':<20} {'P1 Wins':>8} {'P2 Wins':>8} {'Draws':>6} "
          f"{'Avg Moves':>10} {'Avg Time':>9}")
    print(f"  {'-'*64}")
    for m in all_results:
        label = f"{m['p1_skill']} vs {m['p2_skill']}"
        print(f"  {label:<20} {m['p1_wins']:>5}/{m['num_games']:<3} "
              f"{m['p2_wins']:>5}/{m['num_games']:<3} {m['draws']:>4}   "
              f"{m['avg_moves']:>8.1f}   {m['avg_game_time']:>7.1f}s")
    print(f"\n  Total benchmark time: {total_time:.1f}s")

    # Export
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(_HERE, "results", f"benchmark_{timestamp}.txt")
    export_results(all_results, filepath)
    print(f"\n  Results exported to: {filepath}")
    print()


if __name__ == "__main__":
    main()
