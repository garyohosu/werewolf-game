import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from natural_text_normalizer import NaturalTextNormalizer  # noqa: E402


def test_natural_speech_becomes_json() -> None:
    result = NaturalTextNormalizer().normalize(
        phase="speech",
        player="Codex",
        role="villager",
        candidates=[],
        public_log="",
        raw_text="私は村人です。理由は、占い師を守りたいからです。",
    )
    assert result.ok is True
    payload = json.loads(result.json_text)
    assert payload["speech"] == "私は村人です。"
    assert payload["reason"] == "占い師を守りたいからです。"


def test_natural_vote_extracts_candidate_and_reason() -> None:
    result = NaturalTextNormalizer().normalize(
        phase="vote",
        player="Codex",
        role="villager",
        candidates=["Claude", "Grok", "agy"],
        public_log="",
        raw_text="Claudeに投票します。理由は発言が占い師を炙っているように見えるためです。",
    )
    assert result.ok is True
    payload = json.loads(result.json_text)
    assert payload == {
        "vote": "Claude",
        "reason": "発言が占い師を炙っているように見えるためです。",
    }


def test_natural_vote_allows_same_candidate_tied_nearest_mentions() -> None:
    result = NaturalTextNormalizer().normalize(
        phase="vote",
        player="Codex",
        role="werewolf",
        candidates=["Claude", "Grok", "agy"],
        public_log="",
        raw_text=(
            "私はClaudeに投票します。\n\n"
            "理由は、Claudeの占い結果が偽だからです。"
            "Grokとagyもその流れに乗りかけています。"
            "偽の黒出しで場を動かしているClaudeに投票するのが筋です。"
        ),
    )
    assert result.ok is True
    assert json.loads(result.json_text)["vote"] == "Claude"


def test_natural_night_extracts_target_and_reason() -> None:
    result = NaturalTextNormalizer().normalize(
        phase="night",
        player="Codex",
        role="seer",
        candidates=["Claude", "Grok", "agy"],
        public_log="",
        raw_text="Grokを占います。理由は発言が控えめで色を見たいためです。",
    )
    assert result.ok is True
    payload = json.loads(result.json_text)
    assert payload == {
        "target": "Grok",
        "reason": "発言が控えめで色を見たいためです。",
    }


def test_multiple_candidates_without_action_anchor_is_ambiguous() -> None:
    result = NaturalTextNormalizer().normalize(
        phase="vote",
        player="Codex",
        role="villager",
        candidates=["Claude", "Grok", "agy"],
        public_log="",
        raw_text="ClaudeもGrokも気になります。もう少し考えたいです。",
    )
    assert result.ok is False
    assert result.error == "missing_or_ambiguous_target"


def test_missing_candidate_fails() -> None:
    result = NaturalTextNormalizer().normalize(
        phase="night",
        player="Codex",
        role="seer",
        candidates=["Claude", "Grok", "agy"],
        public_log="",
        raw_text="いちばん怪しい人を占います。",
    )
    assert result.ok is False
    assert result.error == "missing_or_ambiguous_target"
