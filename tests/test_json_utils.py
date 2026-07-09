"""Unit tests for JsonValidator (SPEC.md 12章). Run: python -m unittest discover tests"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from json_utils import JsonValidator  # noqa: E402


class SpeechValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = JsonValidator()

    def test_valid_speech_is_accepted(self) -> None:
        raw = '{"speech": "hello", "reason": "because"}'
        result = self.validator.validate(raw, "speech", "Claude", [])
        self.assertTrue(result.ok)
        self.assertEqual(result.action, {"speech": "hello", "reason": "because"})
        self.assertIsNone(result.error_type)

    def test_not_json_is_syntax_error(self) -> None:
        result = self.validator.validate("not json at all", "speech", "Claude", [])
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "syntax")

    def test_text_before_and_after_json_is_syntax_error(self) -> None:
        raw = 'Sure, here it is: {"speech": "hi", "reason": "x"} Thanks!'
        result = self.validator.validate(raw, "speech", "Claude", [])
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "syntax")

    def test_markdown_code_fence_is_syntax_error(self) -> None:
        raw = '```json\n{"speech": "hi", "reason": "x"}\n```'
        result = self.validator.validate(raw, "speech", "Claude", [])
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "syntax")

    def test_json_array_top_level_is_syntax_error(self) -> None:
        raw = '["speech", "hi"]'
        result = self.validator.validate(raw, "speech", "Claude", [])
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "syntax")

    def test_missing_required_key_is_semantic_error(self) -> None:
        raw = '{"speech": "hi"}'
        result = self.validator.validate(raw, "speech", "Claude", [])
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "semantic")

    def test_extra_key_is_semantic_error(self) -> None:
        raw = '{"speech": "hi", "reason": "x", "extra": "y"}'
        result = self.validator.validate(raw, "speech", "Claude", [])
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "semantic")

    def test_empty_string_value_is_semantic_error(self) -> None:
        raw = '{"speech": "", "reason": "x"}'
        result = self.validator.validate(raw, "speech", "Claude", [])
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "semantic")

    def test_null_value_is_semantic_error(self) -> None:
        raw = '{"speech": null, "reason": "x"}'
        result = self.validator.validate(raw, "speech", "Claude", [])
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "semantic")

    def test_type_mismatch_is_semantic_error(self) -> None:
        raw = '{"speech": 123, "reason": "x"}'
        result = self.validator.validate(raw, "speech", "Claude", [])
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "semantic")


class VoteAndNightValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = JsonValidator()
        self.candidates = ["Codex", "Grok", "agy"]  # Claude excluded (self)

    def test_valid_vote_is_accepted(self) -> None:
        raw = '{"vote": "Codex", "reason": "because"}'
        result = self.validator.validate(raw, "vote", "Claude", self.candidates)
        self.assertTrue(result.ok)
        self.assertEqual(result.action["vote"], "Codex")

    def test_vote_for_nonexistent_player_is_semantic_error(self) -> None:
        raw = '{"vote": "NoSuchPlayer", "reason": "x"}'
        result = self.validator.validate(raw, "vote", "Claude", self.candidates)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "semantic")

    def test_self_vote_is_semantic_error(self) -> None:
        # candidates already excludes "Claude", so voting for self must fail.
        raw = '{"vote": "Claude", "reason": "x"}'
        result = self.validator.validate(raw, "vote", "Claude", self.candidates)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "semantic")

    def test_valid_night_action_is_accepted(self) -> None:
        raw = '{"target": "Grok", "reason": "because"}'
        result = self.validator.validate(raw, "night", "Codex", self.candidates)
        self.assertTrue(result.ok)
        self.assertEqual(result.action["target"], "Grok")

    def test_night_self_target_is_semantic_error(self) -> None:
        candidates = ["Claude", "Grok", "agy"]  # Codex excluded (self, the seer)
        raw = '{"target": "Codex", "reason": "x"}'
        result = self.validator.validate(raw, "night", "Codex", candidates)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "semantic")


if __name__ == "__main__":
    unittest.main()
