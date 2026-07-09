"""Persistence: game directory numbering/creation and file writes.

SPEC.md v0.6-draft 14, 17 chapters.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

from models import ErrorRecord, GameState, SpeechEntry, VoteEntry

_GAME_DIR_PATTERN = re.compile(r"^game_(\d{4})$")


class LogWriter:
    """Manages logs/games/game_XXXX/ directories and their contents."""

    def __init__(self, logs_root: Path) -> None:
        self._games_root = logs_root
        self._games_root.mkdir(parents=True, exist_ok=True)
        self._errors: Dict[int, List[ErrorRecord]] = {}

    def next_start_game_id(self) -> int:
        """Existing max game_XXXX + 1, or 1 if none exist (14章)."""
        max_id = 0
        for entry in self._games_root.iterdir():
            if not entry.is_dir():
                continue
            match = _GAME_DIR_PATTERN.match(entry.name)
            if match:
                max_id = max(max_id, int(match.group(1)))
        return max_id + 1

    def _game_dir(self, game_id: int) -> Path:
        return self._games_root / f"game_{game_id:04d}"

    def create_game_dir(self, game_id: int) -> None:
        game_dir = self._game_dir(game_id)
        if game_dir.exists():
            raise FileExistsError(
                f"{game_dir} already exists; refusing to overwrite (SPEC.md 14章)"
            )
        game_dir.mkdir(parents=True)
        (game_dir / "raw").mkdir()
        self._errors[game_id] = []

    def init_public_log(self, game_id: int) -> None:
        path = self._game_dir(game_id) / "public_log.md"
        path.write_text(f"# public_log (game_{game_id:04d})\n\n## 発言\n\n", encoding="utf-8")

    def init_results(self, game_id: int) -> None:
        path = self._game_dir(game_id) / "results.md"
        path.write_text(f"# results (game_{game_id:04d})\n\n", encoding="utf-8")

    def save_game_state(self, game_id: int, state: GameState) -> None:
        path = self._game_dir(game_id) / "game_state.json"
        payload = {
            "game_id": state.game_id,
            "phase": state.phase.value,
            "players": {
                name: {"role": player.role.value} for name, player in state.players.items()
            },
            "seer_result": (
                {
                    "seer": state.seer_result.seer,
                    "target": state.seer_result.target,
                    "result": state.seer_result.result,
                }
                if state.seer_result is not None
                else None
            ),
            "executed": state.executed,
            "winner": state.winner,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def append_speech(self, game_id: int, entry: SpeechEntry) -> None:
        path = self._game_dir(game_id) / "public_log.md"
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"- **{entry.player}**: {entry.speech}\n")

    def append_votes(self, game_id: int, votes: List[VoteEntry]) -> None:
        path = self._game_dir(game_id) / "public_log.md"
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n## 投票結果\n\n")
            for vote in votes:
                f.write(f"- {vote.player} -> {vote.vote}\n")

    def append_execution_result(self, game_id: int, executed: str, winner: str) -> None:
        path = self._game_dir(game_id) / "public_log.md"
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n## 処刑結果\n\n")
            f.write(f"- 処刑されたプレイヤー: {executed}\n")
            f.write(f"- 勝利陣営: {winner}\n")

    def save_raw_response(
        self, game_id: int, seq: int, phase: str, player: str, error_type: str, raw: str
    ) -> None:
        raw_dir = self._game_dir(game_id) / "raw"
        filename = f"{seq:02d}_{phase}_{player}_{error_type}.txt"
        (raw_dir / filename).write_text(raw, encoding="utf-8")

    def record_error(self, game_id: int, seq: int, phase: str, player: str, error_type: str) -> None:
        self._errors.setdefault(game_id, []).append(
            ErrorRecord(seq=seq, phase=phase, player=player, error_type=error_type)
        )

    def save_results(
        self,
        game_id: int,
        state: GameState,
        speeches: List[SpeechEntry],
        votes: List[VoteEntry],
    ) -> None:
        path = self._game_dir(game_id) / "results.md"
        lines = [f"# results (game_{game_id:04d})", ""]

        lines.append("## 役職一覧")
        for name, player in state.players.items():
            lines.append(f"- {name}: {player.role.value}")
        lines.append("")

        lines.append("## 発言")
        for entry in speeches:
            marker = " (失敗)" if entry.failed else ""
            lines.append(f"- {entry.player}{marker}: {entry.speech}")
        lines.append("")

        lines.append("## 投票")
        for vote in votes:
            marker = " (失敗)" if vote.failed else ""
            lines.append(f"- {vote.player} -> {vote.vote}{marker}")
        lines.append("")

        if state.seer_result is not None:
            lines.append("## 占い結果")
            lines.append(
                f"- {state.seer_result.seer} が {state.seer_result.target} を占い、"
                f"結果は {state.seer_result.result}"
            )
            lines.append("")

        lines.append("## 勝敗")
        lines.append(f"- 処刑されたプレイヤー: {state.executed}")
        lines.append(f"- 勝利陣営: {state.winner}")
        lines.append("")

        errors = self._errors.get(game_id, [])
        if errors:
            lines.append("## エラー記録")
            for err in errors:
                lines.append(
                    f"- seq={err.seq} phase={err.phase} player={err.player} "
                    f"error_type={err.error_type}"
                )
            lines.append("")

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
