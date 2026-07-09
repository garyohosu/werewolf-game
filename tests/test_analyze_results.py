"""Unit tests for analyze_results.py."""
from __future__ import annotations

import json
from pathlib import Path
import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from analyze_results import analyze, format_json, format_markdown  # noqa: E402


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_analyze_valid_and_invalid_games(tmp_path: Path) -> None:
    logs_root = tmp_path / "games"
    logs_root.mkdir()

    # 1. Valid finished game -> villager wins
    g1 = logs_root / "game_0001"
    g1.mkdir()
    _write_json(g1 / "game_state.json", {
        "game_id": 1,
        "phase": "finished",
        "players": {
            "Claude": {"role": "villager"},
            "Codex": {"role": "werewolf"},
            "Grok": {"role": "seer"},
            "agy": {"role": "villager"}
        },
        "winner": "villager",
        "executed": "Codex"
    })

    # 2. Valid finished game -> werewolf wins
    g2 = logs_root / "game_0002"
    g2.mkdir()
    _write_json(g2 / "game_state.json", {
        "game_id": 2,
        "phase": "finished",
        "players": {
            "Claude": {"role": "villager"},
            "Codex": {"role": "werewolf"},
            "Grok": {"role": "seer"},
            "agy": {"role": "villager"}
        },
        "winner": "werewolf",
        "executed": "Grok"
    })

    # 3. Unfinished game -> skipped
    g3 = logs_root / "game_0003"
    g3.mkdir()
    _write_json(g3 / "game_state.json", {
        "game_id": 3,
        "phase": "speech",
        "players": {},
        "winner": "none",
        "executed": "none"
    })

    # 4. JSON corruption -> skipped
    g4 = logs_root / "game_0004"
    g4.mkdir()
    (g4 / "game_state.json").write_text("{invalid json", encoding="utf-8")

    # 5. Missing keys -> skipped
    g5 = logs_root / "game_0005"
    g5.mkdir()
    _write_json(g5 / "game_state.json", {
        "game_id": 5,
        "phase": "finished"
    })

    results = analyze(logs_root)

    assert results["overview"]["total_games"] == 5
    assert results["overview"]["valid_games"] == 2
    assert results["overview"]["skipped_games"] == 3

    assert results["overview"]["villager_wins"] == 1
    assert results["overview"]["werewolf_wins"] == 1
    assert results["overview"]["villager_win_rate"] == 0.5
    assert results["overview"]["werewolf_win_rate"] == 0.5

    assert results["players"]["Claude"]["games"] == 2
    assert results["players"]["Claude"]["wins"] == 1
    assert results["players"]["Claude"]["win_rate"] == 0.5

    assert results["players"]["Codex"]["games"] == 2
    assert results["players"]["Codex"]["wins"] == 1
    assert results["players"]["Codex"]["win_rate"] == 0.5

    assert results["roles"]["werewolf"]["assignments"] == 2
    assert results["roles"]["werewolf"]["wins"] == 1
    assert results["roles"]["werewolf"]["win_rate"] == 0.5

    assert results["players"]["Codex"]["executed_count"] == 1
    assert results["players"]["Grok"]["executed_count"] == 1
    assert results["players"]["Claude"]["executed_count"] == 0

    assert any("JSON破損" in w for w in results["warnings"])
    assert any("試合未完了" in w for w in results["warnings"])
    assert any("必須キー欠落" in w for w in results["warnings"])


def test_analyze_no_games(tmp_path: Path) -> None:
    logs_root = tmp_path / "games"
    logs_root.mkdir()

    results = analyze(logs_root)
    assert results["overview"]["total_games"] == 0
    assert results["overview"]["valid_games"] == 0
    assert len(results["warnings"]) == 1
    assert "No game directories" in results["warnings"][0]


def test_analyze_non_existent_logs_root() -> None:
    non_existent = Path("non_existent_path_xyz")
    with pytest.raises(SystemExit) as exc_info:
        analyze(non_existent)
    assert exc_info.value.code == 1


def test_formats(tmp_path: Path) -> None:
    logs_root = tmp_path / "games"
    logs_root.mkdir()
    g1 = logs_root / "game_0001"
    g1.mkdir()
    _write_json(g1 / "game_state.json", {
        "game_id": 1,
        "phase": "finished",
        "players": {
            "Claude": {"role": "villager"},
            "Codex": {"role": "werewolf"},
            "Grok": {"role": "seer"},
            "agy": {"role": "villager"}
        },
        "winner": "villager",
        "executed": "Codex"
    })

    results = analyze(logs_root)

    md_content = format_markdown(results)
    assert "# Werewolf Game Summary" in md_content
    assert "## Overview" in md_content
    assert "- Total games: 1" in md_content
    assert "| Player | Games |" in md_content
    assert "| Claude | 1 | 1 | 1.0000 |" in md_content
    assert "| werewolf | 1 | 0 | 0.0000 |" in md_content

    json_content = format_json(results)
    parsed = json.loads(json_content)
    assert "overview" in parsed
    assert "players" in parsed
    assert "roles" in parsed
    assert "warnings" in parsed
    assert parsed["overview"]["total_games"] == 1


def test_output_file_generation(tmp_path: Path) -> None:
    from unittest.mock import patch
    import sys
    from analyze_results import main

    logs_root = tmp_path / "games"
    logs_root.mkdir()
    g1 = logs_root / "game_0001"
    g1.mkdir()
    _write_json(g1 / "game_state.json", {
        "game_id": 1,
        "phase": "finished",
        "players": {
            "Claude": {"role": "villager"},
            "Codex": {"role": "werewolf"},
            "Grok": {"role": "seer"},
            "agy": {"role": "villager"}
        },
        "winner": "villager",
        "executed": "Codex"
    })

    output_file = tmp_path / "reports" / "summary.md"

    test_args = [
        "analyze_results.py",
        "--logs-root", str(logs_root),
        "--output", str(output_file),
        "--format", "markdown"
    ]

    with patch.object(sys, "argv", test_args):
        main()

    assert output_file.exists()
    file_content = output_file.read_text(encoding="utf-8")
    assert "# Werewolf Game Summary" in file_content
