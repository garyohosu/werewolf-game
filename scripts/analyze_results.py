#!/usr/bin/env python3
"""Phase 4: Multiple games results aggregation script.

Aggregates logs/games/game_XXXX/game_state.json files and produces
markdown/json reports.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze werewolf game results.")
    parser.add_argument(
        "--logs-root",
        type=Path,
        default=Path("logs/games"),
        help="Path to the logs directory containing game_XXXX subdirectories (default: logs/games)"
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to save the summary report"
    )
    return parser.parse_args()


def analyze(logs_root: Path) -> Dict[str, Any]:
    if not logs_root.exists() or not logs_root.is_dir():
        print(f"Error: logs-root directory '{logs_root}' does not exist.", file=sys.stderr)
        sys.exit(1)

    game_files = []
    for p in logs_root.iterdir():
        if p.is_dir() and p.name.startswith("game_"):
            state_file = p / "game_state.json"
            if state_file.exists():
                game_files.append((p.name, state_file))

    # Sort by game directory name (e.g. game_0001, game_0002, ...)
    game_files.sort(key=lambda x: x[0])

    total_games = len(game_files)
    valid_games = 0
    skipped_games = 0
    warnings: List[str] = []

    villager_wins = 0
    werewolf_wins = 0

    player_stats: Dict[str, Dict[str, Any]] = {}
    role_stats = {
        "werewolf": {"assignments": 0, "wins": 0},
        "seer": {"assignments": 0, "wins": 0},
        "villager": {"assignments": 0, "wins": 0},
    }

    if total_games == 0:
        warnings.append("No game directories found under logs-root.")

    for game_dir_name, state_file in game_files:
        try:
            content = state_file.read_text(encoding="utf-8")
            data = json.loads(content)
        except json.JSONDecodeError:
            warnings.append(f"skipped {game_dir_name}: JSON破損")
            skipped_games += 1
            continue
        except OSError as exc:
            warnings.append(f"skipped {game_dir_name}: ファイル読込失敗 ({exc})")
            skipped_games += 1
            continue

        required_keys = {"game_id", "phase", "players", "winner", "executed"}
        if not required_keys.issubset(data):
            missing = required_keys - set(data)
            warnings.append(f"skipped {game_dir_name}: 必須キー欠落 ({', '.join(sorted(missing))})")
            skipped_games += 1
            continue

        phase = data["phase"]
        if phase != "finished":
            warnings.append(f"skipped {game_dir_name}: 試合未完了 (phase: {phase})")
            skipped_games += 1
            continue

        players = data["players"]
        winner = data["winner"]
        executed = data["executed"]

        if not isinstance(players, dict):
            warnings.append(f"skipped {game_dir_name}: players形式不正 (dict型でない)")
            skipped_games += 1
            continue

        if winner not in {"villager", "werewolf"}:
            warnings.append(f"skipped {game_dir_name}: winner不正 ({winner})")
            skipped_games += 1
            continue

        if executed not in players:
            warnings.append(f"skipped {game_dir_name}: executed不正 (プレイヤー一覧に不在: {executed})")
            skipped_games += 1
            continue

        player_role_error = False
        for p_name, p_state in players.items():
            if not isinstance(p_state, dict) or "role" not in p_state:
                player_role_error = True
                warnings.append(f"skipped {game_dir_name}: player {p_name} のrole情報が見つかりません")
                break
            role_val = p_state["role"]
            if role_val not in {"werewolf", "seer", "villager"}:
                player_role_error = True
                warnings.append(f"skipped {game_dir_name}: player {p_name} のrole値が不正です ({role_val})")
                break
        if player_role_error:
            skipped_games += 1
            continue

        valid_games += 1

        if winner == "villager":
            villager_wins += 1
        elif winner == "werewolf":
            werewolf_wins += 1

        for p_name, p_state in players.items():
            role = p_state["role"]

            if p_name not in player_stats:
                player_stats[p_name] = {
                    "games": 0,
                    "wins": 0,
                    "role_counts": {"werewolf": 0, "seer": 0, "villager": 0},
                    "role_wins": {"werewolf": 0, "seer": 0, "villager": 0},
                    "executed_count": 0,
                }

            stats = player_stats[p_name]
            stats["games"] += 1
            stats["role_counts"][role] += 1

            is_win = False
            if winner == "werewolf" and role == "werewolf":
                is_win = True
            elif winner == "villager" and role in {"seer", "villager"}:
                is_win = True

            if is_win:
                stats["wins"] += 1
                stats["role_wins"][role] += 1

            if executed == p_name:
                stats["executed_count"] += 1

            role_stats[role]["assignments"] += 1
            if is_win:
                role_stats[role]["wins"] += 1

    villager_win_rate = villager_wins / valid_games if valid_games > 0 else 0.0
    werewolf_win_rate = werewolf_wins / valid_games if valid_games > 0 else 0.0

    for p_name, stats in player_stats.items():
        stats["win_rate"] = stats["wins"] / stats["games"] if stats["games"] > 0 else 0.0

    for r_name, stats in role_stats.items():
        stats["win_rate"] = stats["wins"] / stats["assignments"] if stats["assignments"] > 0 else 0.0

    return {
        "overview": {
            "total_games": total_games,
            "valid_games": valid_games,
            "skipped_games": skipped_games,
            "villager_wins": villager_wins,
            "werewolf_wins": werewolf_wins,
            "villager_win_rate": villager_win_rate,
            "werewolf_win_rate": werewolf_win_rate,
        },
        "players": player_stats,
        "roles": role_stats,
        "warnings": warnings,
    }


def format_markdown(data: Dict[str, Any]) -> str:
    ov = data["overview"]
    lines = [
        "# Werewolf Game Summary",
        "",
        "## Overview",
        f"- Total games: {ov['total_games']}",
        f"- Valid games: {ov['valid_games']}",
        f"- Skipped games: {ov['skipped_games']}",
        f"- Villager wins: {ov['villager_wins']}",
        f"- Werewolf wins: {ov['werewolf_wins']}",
        f"- Villager win rate: {ov['villager_win_rate']:.4f}",
        f"- Werewolf win rate: {ov['werewolf_win_rate']:.4f}",
        "",
        "## Player Summary",
        "| Player | Games | Wins | Win Rate | Werewolf Wins | Seer Wins | Villager Wins | Executed |",
        "|---|---|---|---|---|---|---|---|",
    ]

    sorted_players = sorted(data["players"].keys())
    for name in sorted_players:
        p = data["players"][name]

        def r_str(role: str) -> str:
            w = p["role_wins"][role]
            c = p["role_counts"][role]
            return f"{w}/{c}"

        lines.append(
            f"| {name} | {p['games']} | {p['wins']} | {p['win_rate']:.4f} | "
            f"{r_str('werewolf')} | {r_str('seer')} | {r_str('villager')} | {p['executed_count']} |"
        )

    lines.append("")
    lines.append("## Role Summary")
    lines.append("| Role | Assignments | Wins | Win Rate |")
    lines.append("|---|---|---|---|")

    for role in ["werewolf", "seer", "villager"]:
        r = data["roles"][role]
        lines.append(f"| {role} | {r['assignments']} | {r['wins']} | {r['win_rate']:.4f} |")

    lines.append("")
    lines.append("## Warnings")
    if data["warnings"]:
        for w in data["warnings"]:
            lines.append(f"- {w}")
    else:
        lines.append("None")

    return "\n".join(lines) + "\n"


def format_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    args = parse_args()
    results = analyze(args.logs_root)

    if args.format == "json":
        output_content = format_json(results)
    else:
        output_content = format_markdown(results)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_content, encoding="utf-8")
    else:
        sys.stdout.write(output_content)


if __name__ == "__main__":
    main()
