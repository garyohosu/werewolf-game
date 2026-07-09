import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from agents import ConfigLoader  # noqa: E402


def _valid_config() -> dict:
    return {
        name: {"command": name.lower(), "args": [], "prompt_mode": "arg"}
        for name in ["Claude", "Codex", "Grok", "agy"]
    }


def _write_config(tmp_path: Path, payload) -> Path:
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_config_preserves_definition_order(tmp_path: Path) -> None:
    configs = ConfigLoader().load(_write_config(tmp_path, _valid_config()))
    assert [config.name for config in configs] == ["Claude", "Codex", "Grok", "agy"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.pop("agy"),
        lambda data: data["Claude"].pop("command"),
        lambda data: data["Claude"].update(command=""),
        lambda data: data["Claude"].update(args="not-an-array"),
        lambda data: data["Claude"].update(prompt_mode="invalid"),
    ],
)
def test_invalid_config_is_rejected(tmp_path: Path, mutate) -> None:
    data = _valid_config()
    mutate(data)
    with pytest.raises(ValueError):
        ConfigLoader().load(_write_config(tmp_path, data))


def test_invalid_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "agents.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        ConfigLoader().load(path)


def test_duplicate_player_name_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "agents.json"
    path.write_text(
        '{"Claude":{"command":"a","args":[],"prompt_mode":"arg"},'
        '"Codex":{"command":"b","args":[],"prompt_mode":"arg"},'
        '"Grok":{"command":"c","args":[],"prompt_mode":"arg"},'
        '"agy":{"command":"d","args":[],"prompt_mode":"stdin"},'
        '"Claude":{"command":"e","args":[],"prompt_mode":"arg"}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate player name"):
        ConfigLoader().load(path)
