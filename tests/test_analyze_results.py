import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from analyze_results import aggregate, main, render_markdown  # noqa: E402


PLAYERS = ["Claude", "Codex", "Grok", "agy"]


def write_game(
    logs_root: Path,
    game_id: int,
    roles: dict,
    executed: str,
    winner: str,
    *,
    phase: str = "finished",
    votes: dict | None = None,
) -> Path:
    game_dir = logs_root / f"game_{game_id:04d}"
    game_dir.mkdir(parents=True)
    state = {
        "game_id": game_id,
        "phase": phase,
        "players": {player: {"role": role} for player, role in roles.items()},
        "seer_result": None,
        "executed": executed,
        "winner": winner,
    }
    (game_dir / "game_state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )
    if votes is not None:
        lines = ["# public_log", "", "## 投票結果", ""]
        lines.extend(f"- {voter} -> {target}" for voter, target in votes.items())
        (game_dir / "public_log.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return game_dir


@pytest.fixture
def sample_logs(tmp_path: Path) -> Path:
    logs_root = tmp_path / "games"
    logs_root.mkdir()
    write_game(
        logs_root,
        1,
        {"Claude": "werewolf", "Codex": "seer", "Grok": "villager", "agy": "villager"},
        "Claude",
        "villager",
        votes={"Claude": "Codex", "Codex": "Claude", "Grok": "Claude", "agy": "Codex"},
    )
    write_game(
        logs_root,
        2,
        {"Claude": "villager", "Codex": "werewolf", "Grok": "seer", "agy": "villager"},
        "Claude",
        "werewolf",
        votes={"Claude": "Codex", "Codex": "Claude", "Grok": "Claude", "agy": "Claude"},
    )
    return logs_root


def test_aggregate_finished_games_and_win_rates(sample_logs: Path) -> None:
    data = aggregate(sample_logs).as_dict()
    overview = data["overview"]
    assert overview["total_games"] == 2
    assert overview["valid_games"] == 2
    assert overview["skipped_games"] == 0
    assert overview["villager_wins"] == 1
    assert overview["werewolf_wins"] == 1
    assert overview["villager_win_rate"] == 0.5
    assert overview["werewolf_win_rate"] == 0.5
    assert overview["tie_break_executions"] == 1
    assert overview["tie_break_detectable_games"] == 2


def test_player_and_role_stats(sample_logs: Path) -> None:
    data = aggregate(sample_logs).as_dict()
    assert data["players"]["Claude"]["games"] == 2
    assert data["players"]["Claude"]["wins"] == 0
    assert data["players"]["Claude"]["win_rate"] == 0.0
    assert data["players"]["Claude"]["executed"] == 2
    assert data["players"]["Codex"]["wins"] == 2
    assert data["players"]["Codex"]["roles"]["werewolf"]["win_rate"] == 1.0
    assert data["players"]["Codex"]["roles"]["seer"]["win_rate"] == 1.0
    assert data["players"]["Grok"]["votes_for_executed_werewolf"] == 1
    assert data["roles"]["werewolf"] == {"assignments": 2, "wins": 1, "win_rate": 0.5}
    assert data["roles"]["seer"] == {"assignments": 2, "wins": 1, "win_rate": 0.5}
    assert data["roles"]["villager"] == {"assignments": 4, "wins": 2, "win_rate": 0.5}


def test_unfinished_game_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / "games"
    root.mkdir()
    write_game(
        root,
        1,
        {"Claude": "werewolf", "Codex": "seer", "Grok": "villager", "agy": "villager"},
        "Claude",
        "villager",
        phase="vote",
    )
    summary = aggregate(root)
    assert (summary.total_games, summary.valid_games, summary.skipped_games) == (1, 0, 1)
    assert "not 'finished'" in summary.warnings[0]


def test_broken_json_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / "games"
    game_dir = root / "game_0001"
    game_dir.mkdir(parents=True)
    (game_dir / "game_state.json").write_text("{", encoding="utf-8")
    summary = aggregate(root)
    assert summary.skipped_games == 1
    assert summary.valid_games == 0


def test_missing_required_key_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / "games"
    game_dir = root / "game_0001"
    game_dir.mkdir(parents=True)
    (game_dir / "game_state.json").write_text(
        json.dumps({"game_id": 1, "phase": "finished"}), encoding="utf-8"
    )
    summary = aggregate(root)
    assert summary.skipped_games == 1
    assert "missing required keys" in summary.warnings[0]


def test_no_game_directories_is_success_with_warning(tmp_path: Path) -> None:
    summary = aggregate(tmp_path)
    assert summary.total_games == 0
    assert summary.valid_games == 0
    assert summary.warnings


def test_nonexistent_logs_root_returns_nonzero(tmp_path: Path, capsys) -> None:
    assert main(["--logs-root", str(tmp_path / "missing")]) != 0
    assert "does not exist" in capsys.readouterr().err


def test_markdown_output(sample_logs: Path, capsys) -> None:
    assert main(["--logs-root", str(sample_logs), "--format", "markdown"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("# Werewolf Game Summary")
    assert "## Player Summary" in output
    assert "| Claude | 2 | 0 | 0.00%" in output


def test_json_output(sample_logs: Path, capsys) -> None:
    assert main(["--logs-root", str(sample_logs), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"overview", "players", "roles", "warnings"}
    assert payload["overview"]["valid_games"] == 2


@pytest.mark.parametrize("output_format", ["markdown", "json"])
def test_output_file_is_written(
    sample_logs: Path, tmp_path: Path, output_format: str, capsys
) -> None:
    output = tmp_path / "reports" / f"summary.{output_format}"
    assert (
        main(
            [
                "--logs-root",
                str(sample_logs),
                "--format",
                output_format,
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.exists()
    assert capsys.readouterr().out == ""


def test_missing_public_log_does_not_invalidate_game(tmp_path: Path) -> None:
    root = tmp_path / "games"
    root.mkdir()
    write_game(
        root,
        1,
        {"Claude": "werewolf", "Codex": "seer", "Grok": "villager", "agy": "villager"},
        "Claude",
        "villager",
    )
    summary = aggregate(root)
    assert summary.valid_games == 1
    assert summary.tie_break_detectable_games == 0
    assert summary.tie_break_executions == 0
