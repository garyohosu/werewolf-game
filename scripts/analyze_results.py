#!/usr/bin/env python3
"""Aggregate completed One Night Werewolf game logs.

The authoritative input is logs/games/game_XXXX/game_state.json.
public_log.md is optional and used only for vote-derived metrics.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOGS_ROOT = REPO_ROOT / "logs" / "games"
ROLES = ("werewolf", "seer", "villager")
WINNERS = ("villager", "werewolf")
GAME_DIR_PATTERN = re.compile(r"^game_(\d{4})$")
VOTE_PATTERN = re.compile(r"^- ([^\s]+) -> ([^\s]+)(?:\s.*)?$")


@dataclass
class RoleStats:
    assignments: int = 0
    wins: int = 0

    def as_dict(self) -> dict:
        return {
            "assignments": self.assignments,
            "wins": self.wins,
            "win_rate": rate(self.wins, self.assignments),
        }


@dataclass
class PlayerStats:
    games: int = 0
    wins: int = 0
    executed: int = 0
    votes_for_executed_werewolf: int = 0
    roles: Dict[str, RoleStats] = field(
        default_factory=lambda: {role: RoleStats() for role in ROLES}
    )

    def as_dict(self) -> dict:
        return {
            "games": self.games,
            "wins": self.wins,
            "win_rate": rate(self.wins, self.games),
            "executed": self.executed,
            "votes_for_executed_werewolf": self.votes_for_executed_werewolf,
            "roles": {role: self.roles[role].as_dict() for role in ROLES},
        }


@dataclass
class Summary:
    total_games: int = 0
    valid_games: int = 0
    skipped_games: int = 0
    villager_wins: int = 0
    werewolf_wins: int = 0
    werewolf_executions: int = 0
    tie_break_executions: int = 0
    tie_break_detectable_games: int = 0
    players: Dict[str, PlayerStats] = field(default_factory=dict)
    roles: Dict[str, RoleStats] = field(
        default_factory=lambda: {role: RoleStats() for role in ROLES}
    )
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "overview": {
                "total_games": self.total_games,
                "valid_games": self.valid_games,
                "skipped_games": self.skipped_games,
                "villager_wins": self.villager_wins,
                "werewolf_wins": self.werewolf_wins,
                "villager_win_rate": rate(self.villager_wins, self.valid_games),
                "werewolf_win_rate": rate(self.werewolf_wins, self.valid_games),
                "werewolf_executions": self.werewolf_executions,
                "tie_break_executions": self.tie_break_executions,
                "tie_break_detectable_games": self.tie_break_detectable_games,
            },
            "players": {
                player: self.players[player].as_dict() for player in sorted(self.players)
            },
            "roles": {role: self.roles[role].as_dict() for role in ROLES},
            "warnings": list(self.warnings),
        }


def rate(wins: int, games: int) -> float:
    return wins / games if games else 0.0


def validate_state(data: object, expected_game_id: int) -> dict:
    if not isinstance(data, dict):
        raise ValueError("top level must be an object")
    required = {"game_id", "phase", "players", "executed", "winner"}
    missing = sorted(required - data.keys())
    if missing:
        raise ValueError(f"missing required keys: {', '.join(missing)}")
    if data["game_id"] != expected_game_id:
        raise ValueError("game_id does not match directory name")
    if data["phase"] != "finished":
        raise ValueError(f"phase is {data['phase']!r}, not 'finished'")
    players = data["players"]
    if not isinstance(players, dict) or len(players) != 4:
        raise ValueError("players must contain exactly four entries")
    roles: Dict[str, str] = {}
    for player, value in players.items():
        if not isinstance(player, str) or not player:
            raise ValueError("player names must be non-empty strings")
        if not isinstance(value, dict) or value.get("role") not in ROLES:
            raise ValueError(f"invalid role for player {player!r}")
        roles[player] = value["role"]
    if sorted(roles.values()) != ["seer", "villager", "villager", "werewolf"]:
        raise ValueError("role composition must be werewolf, seer, villager, villager")
    executed = data["executed"]
    winner = data["winner"]
    if executed not in players:
        raise ValueError("executed must name a player")
    if winner not in WINNERS:
        raise ValueError("winner must be 'villager' or 'werewolf'")
    expected_winner = "villager" if roles[executed] == "werewolf" else "werewolf"
    if winner != expected_winner:
        raise ValueError("winner is inconsistent with the executed player's role")
    return data


def read_votes(public_log_path: Path, players: set[str]) -> Optional[Dict[str, str]]:
    try:
        text = public_log_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    votes: Dict[str, str] = {}
    for line in text.splitlines():
        match = VOTE_PATTERN.match(line.strip())
        if not match:
            continue
        voter, target = match.groups()
        if voter in votes or voter not in players or target not in players or voter == target:
            return None
        votes[voter] = target
    return votes if set(votes) == players else None


def aggregate(logs_root: Path) -> Summary:
    if not logs_root.exists() or not logs_root.is_dir():
        raise FileNotFoundError(f"logs root does not exist or is not a directory: {logs_root}")

    summary = Summary()
    game_dirs = sorted(
        (
            (int(match.group(1)), entry)
            for entry in logs_root.iterdir()
            if entry.is_dir() and (match := GAME_DIR_PATTERN.match(entry.name))
        ),
        key=lambda item: item[0],
    )
    summary.total_games = len(game_dirs)
    if not game_dirs:
        summary.warnings.append(f"no game_XXXX directories found in {logs_root}")
        return summary

    for game_id, game_dir in game_dirs:
        state_path = game_dir / "game_state.json"
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            state = validate_state(data, game_id)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            summary.skipped_games += 1
            summary.warnings.append(f"skipped {game_dir.name}: {exc}")
            continue

        summary.valid_games += 1
        winner = state["winner"]
        summary.villager_wins += winner == "villager"
        summary.werewolf_wins += winner == "werewolf"
        summary.werewolf_executions += winner == "villager"

        roles = {player: value["role"] for player, value in state["players"].items()}
        for player, role in roles.items():
            player_stats = summary.players.setdefault(player, PlayerStats())
            won = winner == ("werewolf" if role == "werewolf" else "villager")
            player_stats.games += 1
            player_stats.wins += won
            player_stats.executed += state["executed"] == player
            player_stats.roles[role].assignments += 1
            player_stats.roles[role].wins += won
            summary.roles[role].assignments += 1
            summary.roles[role].wins += won

        votes = read_votes(game_dir / "public_log.md", set(roles))
        if votes is not None:
            summary.tie_break_detectable_games += 1
            counts: Dict[str, int] = {}
            for target in votes.values():
                counts[target] = counts.get(target, 0) + 1
            max_votes = max(counts.values())
            tied = [player for player in roles if counts.get(player, 0) == max_votes]
            summary.tie_break_executions += len(tied) > 1
            if roles[state["executed"]] == "werewolf":
                for voter, target in votes.items():
                    if target == state["executed"]:
                        summary.players[voter].votes_for_executed_werewolf += 1

    return summary


def percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def render_markdown(summary: Summary) -> str:
    data = summary.as_dict()
    overview = data["overview"]
    lines = [
        "# Werewolf Game Summary",
        "",
        "## Overview",
        f"- Total games: {overview['total_games']}",
        f"- Valid games: {overview['valid_games']}",
        f"- Skipped games: {overview['skipped_games']}",
        f"- Villager wins: {overview['villager_wins']}",
        f"- Werewolf wins: {overview['werewolf_wins']}",
        f"- Villager win rate: {percent(overview['villager_win_rate'])}",
        f"- Werewolf win rate: {percent(overview['werewolf_win_rate'])}",
        f"- Werewolf executions: {overview['werewolf_executions']}",
        f"- Tie-break executions: {overview['tie_break_executions']}",
        f"- Tie-break detectable games: {overview['tie_break_detectable_games']}",
        "",
        "## Player Summary",
        "| Player | Games | Wins | Win Rate | Werewolf W/A (Rate) | Seer W/A (Rate) | Villager W/A (Rate) | Executed | Wolf Execution Votes |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for player, stats in data["players"].items():
        role_cells = []
        for role in ROLES:
            role_stats = stats["roles"][role]
            role_cells.append(
                f"{role_stats['wins']}/{role_stats['assignments']} "
                f"({percent(role_stats['win_rate'])})"
            )
        lines.append(
            f"| {player} | {stats['games']} | {stats['wins']} | "
            f"{percent(stats['win_rate'])} | {' | '.join(role_cells)} | "
            f"{stats['executed']} | {stats['votes_for_executed_werewolf']} |"
        )

    lines.extend(
        [
            "",
            "## Role Summary",
            "| Role | Assignments | Wins | Win Rate |",
            "|---|---:|---:|---:|",
        ]
    )
    for role, stats in data["roles"].items():
        lines.append(
            f"| {role} | {stats['assignments']} | {stats['wins']} | "
            f"{percent(stats['win_rate'])} |"
        )
    lines.extend(["", "## Warnings"])
    if data["warnings"]:
        lines.extend(f"- {warning}" for warning in data["warnings"])
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate werewolf game results")
    parser.add_argument("--logs-root", type=Path, default=DEFAULT_LOGS_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        summary = aggregate(args.logs_root)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        output = json.dumps(summary.as_dict(), ensure_ascii=False, indent=2) + "\n"
    else:
        output = render_markdown(summary)

    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        except OSError as exc:
            print(f"error: failed to write {args.output}: {exc}", file=sys.stderr)
            return 1
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
