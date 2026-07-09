"""Unit/integration tests for PromptBuilder (CLASS.md, prompts/*.md)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from agents import PromptBuilder  # noqa: E402
from models import Role  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_PROMPTS_DIR = REPO_ROOT / "prompts"

_PLAYER_NAMES = ["Claude", "Codex", "Grok", "agy"]


def _write(path: Path, body: str) -> None:
    path.write_text(
        "# stub\n\n## 用途\n\nstub file for tests.\n\n## 本文\n\n```text\n" + body + "\n```\n",
        encoding="utf-8",
    )


def _make_synthetic_prompts_dir(tmp_path: Path) -> Path:
    """A minimal synthetic prompts/ tree, independent of the real templates,
    so unit tests don't break if the real wording in prompts/*.md changes."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()

    _write(prompts_dir / "common_player_prompt.md", "COMMON for {{player_name}} among {{player_list}}.")
    _write(prompts_dir / "villager_prompt.md", "VILLAGER role for {{player_name}}.")
    _write(prompts_dir / "seer_prompt.md", "SEER role for {{player_name}}.")
    _write(prompts_dir / "werewolf_prompt.md", "WEREWOLF role for {{player_name}}.")
    _write(
        prompts_dir / "night_seer_prompt.md",
        'NIGHT for {{player_name}}, candidates={{candidates}}. {"target":"...","reason":"..."}',
    )
    _write(
        prompts_dir / "speech_prompt.md",
        'SPEECH for {{player_name}}. log={{public_log}} seer={{seer_result_summary}} '
        '{"speech":"...","reason":"..."}',
    )
    _write(
        prompts_dir / "vote_prompt.md",
        'VOTE for {{player_name}}, candidates={{candidates}}. log={{public_log}} '
        'seer={{seer_result_summary}} {"vote":"...","reason":"..."}',
    )
    return prompts_dir


@pytest.fixture
def builder(tmp_path: Path) -> PromptBuilder:
    prompts_dir = _make_synthetic_prompts_dir(tmp_path)
    return PromptBuilder(prompts_dir, _PLAYER_NAMES)


def test_night_prompt_concatenates_common_seer_and_night_in_order(builder: PromptBuilder) -> None:
    prompt = builder.build_night_prompt("Claude", ["Codex", "Grok", "agy"])
    common_idx = prompt.index("COMMON for Claude")
    seer_idx = prompt.index("SEER role for Claude")
    night_idx = prompt.index("NIGHT for Claude")
    assert common_idx < seer_idx < night_idx


def test_night_prompt_substitutes_player_list_and_candidates(builder: PromptBuilder) -> None:
    prompt = builder.build_night_prompt("Claude", ["Codex", "Grok", "agy"])
    assert "among Claude、Codex、Grok、agy" in prompt
    assert "candidates=Codex、Grok、agy" in prompt
    assert "{{" not in prompt


def test_speech_prompt_uses_role_specific_template(builder: PromptBuilder) -> None:
    prompt = builder.build_speech_prompt(
        "Grok", Role.WEREWOLF, public_log="Claude: hi", seer_result_summary=""
    )
    assert "WEREWOLF role for Grok" in prompt
    assert "SEER role" not in prompt
    assert "VILLAGER role" not in prompt
    assert "log=Claude: hi" in prompt
    assert "seer=" in prompt  # empty seer_result_summary still renders, just blank
    assert "{{" not in prompt


def test_speech_prompt_villager_role(builder: PromptBuilder) -> None:
    prompt = builder.build_speech_prompt("Codex", Role.VILLAGER, public_log="", seer_result_summary="")
    assert "VILLAGER role for Codex" in prompt


def test_vote_prompt_includes_seer_result_summary_when_provided(builder: PromptBuilder) -> None:
    prompt = builder.build_vote_prompt(
        "Claude",
        Role.SEER,
        candidates=["Codex", "Grok", "agy"],
        public_log="Codex: hi\nGrok: hi",
        seer_result_summary="Grok was werewolf",
    )
    assert "SEER role for Claude" in prompt
    assert "candidates=Codex、Grok、agy" in prompt
    assert "seer=Grok was werewolf" in prompt
    assert "{{" not in prompt


def test_each_call_is_independent_no_shared_mutable_state(builder: PromptBuilder) -> None:
    # {{player_list}} legitimately mentions all 4 names in every prompt, so
    # this checks role/content leakage between calls, not name occurrence.
    first = builder.build_speech_prompt("Claude", Role.SEER, public_log="A", seer_result_summary="X")
    second = builder.build_speech_prompt("Codex", Role.VILLAGER, public_log="B", seer_result_summary="")

    assert "SEER role for Claude" in first
    assert "VILLAGER role for Claude" not in first
    assert "log=A" in first and "log=B" not in first

    assert "VILLAGER role for Codex" in second
    assert "SEER role for Codex" not in second
    assert "log=B" in second and "log=A" not in second


def test_leftover_placeholder_raises(tmp_path: Path) -> None:
    prompts_dir = _make_synthetic_prompts_dir(tmp_path)
    # Introduce an unresolvable placeholder into the phase template.
    _write(prompts_dir / "night_seer_prompt.md", "NIGHT {{player_name}} {{unknown_field}}")
    builder = PromptBuilder(prompts_dir, _PLAYER_NAMES)
    with pytest.raises(ValueError, match="unresolved placeholder"):
        builder.build_night_prompt("Claude", ["Codex", "Grok", "agy"])


def test_missing_body_section_raises(tmp_path: Path) -> None:
    prompts_dir = _make_synthetic_prompts_dir(tmp_path)
    (prompts_dir / "villager_prompt.md").write_text("# no body section here", encoding="utf-8")
    with pytest.raises(ValueError, match="本文"):
        PromptBuilder(prompts_dir, _PLAYER_NAMES)


@pytest.fixture
def real_builder() -> PromptBuilder:
    return PromptBuilder(REAL_PROMPTS_DIR, _PLAYER_NAMES)


_REQUIRED_SAFETY_PHRASES = [
    "ファイルを読みに行ってはいけません",
    "シェルコマンドを実行してはいけません",
    "ゲームマスターであり、プレイヤーとして参加しません",
    "推測や創作で「見た」「知っている」と言ってはいけません",
    "指定されたJSONオブジェクトのみ",
    "コードフェンス",
]


def test_real_night_prompt_loads_and_has_no_leftover_placeholders(real_builder: PromptBuilder) -> None:
    prompt = real_builder.build_night_prompt("Codex", ["Claude", "Grok", "agy"])
    assert "{{" not in prompt
    assert '{"target"' in prompt
    for phrase in _REQUIRED_SAFETY_PHRASES:
        assert phrase in prompt, f"missing safety phrase: {phrase}"


def test_real_speech_prompt_for_each_role(real_builder: PromptBuilder) -> None:
    for role in (Role.VILLAGER, Role.SEER, Role.WEREWOLF):
        prompt = real_builder.build_speech_prompt(
            "Claude", role, public_log="まだ発言はありません。", seer_result_summary=""
        )
        assert "{{" not in prompt
        assert '{"speech"' in prompt
        for phrase in _REQUIRED_SAFETY_PHRASES:
            assert phrase in prompt, f"missing safety phrase for {role}: {phrase}"


def test_real_vote_prompt_with_seer_result_summary(real_builder: PromptBuilder) -> None:
    prompt = real_builder.build_vote_prompt(
        "Claude",
        Role.SEER,
        candidates=["Codex", "Grok", "agy"],
        public_log="Codex: hello\nGrok: hi",
        seer_result_summary="あなたの占い結果: Grokはwerewolfでした。",
    )
    assert "{{" not in prompt
    assert '{"vote"' in prompt
    assert "あなたの占い結果: Grokはwerewolfでした。" in prompt


def test_real_prompts_do_not_contain_markdown_code_fences_in_body() -> None:
    # The assembled body text itself must not teach the model to wrap its
    # own answer in a fence -- i.e. no ``` characters inside the "## 本文"
    # block of any prompt file.
    builder = PromptBuilder(REAL_PROMPTS_DIR, _PLAYER_NAMES)
    prompt = builder.build_speech_prompt(
        "Claude", Role.VILLAGER, public_log="", seer_result_summary=""
    )
    assert "```" not in prompt
