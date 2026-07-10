import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from probe_codex_player import validate_stdout  # noqa: E402


def test_validate_simple_speech_ok() -> None:
    result = validate_stdout('{"speech":"テスト","reason":"確認"}', "simple_speech")
    assert result.json_parsed is True
    assert result.schema_ok is True
    assert result.error_type is None


def test_validate_syntax_error() -> None:
    result = validate_stdout("承知しました", "compact_speech")
    assert result.json_parsed is False
    assert result.schema_ok is False
    assert result.error_type == "syntax"


def test_validate_rejects_status_json() -> None:
    result = validate_stdout('{"status":"ok"}', "compact_speech")
    assert result.json_parsed is True
    assert result.schema_ok is False
    assert result.error_type == "semantic"


def test_validate_vote_candidate() -> None:
    ok = validate_stdout('{"vote":"Claude","reason":"怪しいため"}', "compact_vote")
    assert ok.schema_ok is True

    bad = validate_stdout('{"vote":"Codex","reason":"自分です"}', "compact_vote")
    assert bad.schema_ok is False
    assert bad.error_type == "semantic"


def test_validate_night_target_candidate() -> None:
    ok = validate_stdout('{"target":"Grok","reason":"確認したい"}', "compact_night")
    assert ok.schema_ok is True

    bad = validate_stdout('{"target":"Unknown","reason":"確認したい"}', "compact_night")
    assert bad.schema_ok is False
    assert bad.error_type == "semantic"
