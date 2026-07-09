"""Strict JSON syntax/semantic validation for AI player responses.

SPEC.md v0.6-draft 11, 12 chapters. SEQUENCE.md 7 chapter.
"""
from __future__ import annotations

import json
from typing import Iterable, Optional

from models import ValidationResult

# 11章: phase -> required keys (extra keys are rejected, 12.2章)
_SCHEMAS = {
    "night": {"target", "reason"},
    "speech": {"speech", "reason"},
    "vote": {"vote", "reason"},
}

# phase -> key whose value must be a valid candidate name
_TARGET_KEY = {"night": "target", "vote": "vote"}


class JsonValidator:
    """Validates raw AI responses against SPEC.md 12.1/12.2 chapters."""

    def validate(
        self,
        raw_response: str,
        phase: str,
        player: str,
        candidates: Iterable[str],
    ) -> ValidationResult:
        if phase not in _SCHEMAS:
            raise ValueError(f"unknown phase: {phase}")

        parsed = self._parse_strict_json(raw_response)
        if parsed is None:
            return ValidationResult(ok=False, action=None, error_type="syntax")

        semantic_error = self._check_semantics(parsed, phase, candidates)
        if semantic_error:
            return ValidationResult(ok=False, action=None, error_type="semantic")

        return ValidationResult(ok=True, action=parsed, error_type=None)

    @staticmethod
    def _parse_strict_json(raw_response: str) -> Optional[dict]:
        """Parses the whole response as a single JSON object.

        Any leading/trailing text or Markdown code fences make json.loads
        fail naturally, which is treated as a syntax error (SEQUENCE.md 7.1).
        """
        try:
            parsed = json.loads(raw_response)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    @staticmethod
    def _check_semantics(parsed: dict, phase: str, candidates: Iterable[str]) -> bool:
        """Returns True if a semantic error is found (12.2章)."""
        expected_keys = _SCHEMAS[phase]
        if set(parsed.keys()) != expected_keys:
            return True

        for key in expected_keys:
            value = parsed[key]
            if not isinstance(value, str) or value == "":
                return True

        target_key = _TARGET_KEY.get(phase)
        if target_key is not None:
            candidate_set = set(candidates)
            # candidates already excludes the acting player, so this single
            # membership check covers both "存在しないプレイヤー名" and
            # "自分自身を対象に指定" (12.2章).
            if parsed[target_key] not in candidate_set:
                return True

        return False
