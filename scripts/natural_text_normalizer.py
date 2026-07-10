"""Local normalization for natural-language AI player responses.

The normalizer only reformats explicit content. It must not infer a vote or
seer target that is not present in the player's text.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence


_DEFAULT_REASON = "Codex natural text response"
_VOTE_ANCHORS = ("投票します", "投票する", "投票先", "票を入れます", "票を入れる", "入れます")
_NIGHT_ANCHORS = ("占います", "占う", "占い先", "占って")
_REASON_PATTERNS = (
    re.compile(r"理由は(?P<reason>.+)", re.DOTALL),
    re.compile(r"理由としては(?P<reason>.+)", re.DOTALL),
    re.compile(r"なぜなら(?P<reason>.+)", re.DOTALL),
)


@dataclass
class NormalizationResult:
    ok: bool
    json_text: Optional[str]
    error: Optional[str]


class NaturalTextNormalizer:
    """Converts natural text into the strict JSON expected by GameEngine."""

    def normalize(
        self,
        phase: str,
        player: str,
        role: str,
        candidates: Sequence[str],
        public_log: str,
        raw_text: str,
    ) -> NormalizationResult:
        text = raw_text.strip()
        if not text:
            return NormalizationResult(False, None, "empty_text")

        if phase == "speech":
            return self._normalize_speech(text)
        if phase == "vote":
            return self._normalize_target_text("vote", text, candidates, _VOTE_ANCHORS)
        if phase == "night":
            return self._normalize_target_text("target", text, candidates, _NIGHT_ANCHORS)
        return NormalizationResult(False, None, f"unsupported_phase:{phase}")

    def _normalize_speech(self, text: str) -> NormalizationResult:
        speech, reason = self._split_speech_and_reason(text)
        payload = {"speech": speech, "reason": reason}
        return NormalizationResult(True, self._dump(payload), None)

    def _normalize_target_text(
        self, key: str, text: str, candidates: Sequence[str], anchors: Sequence[str]
    ) -> NormalizationResult:
        target = self._select_explicit_candidate(text, candidates, anchors)
        if target is None:
            return NormalizationResult(False, None, "missing_or_ambiguous_target")
        payload = {key: target, "reason": self._extract_reason(text)}
        return NormalizationResult(True, self._dump(payload), None)

    def _select_explicit_candidate(
        self, text: str, candidates: Sequence[str], anchors: Sequence[str]
    ) -> Optional[str]:
        mentions = self._candidate_mentions(text, candidates)
        mentioned_candidates = sorted({candidate for candidate, _ in mentions})
        if not mentioned_candidates:
            return None
        if len(mentioned_candidates) == 1:
            return mentioned_candidates[0]

        anchor_positions = [text.find(anchor) for anchor in anchors if text.find(anchor) >= 0]
        if not anchor_positions:
            return None

        scored = []
        for candidate, pos in mentions:
            distance = min(abs(pos - anchor_pos) for anchor_pos in anchor_positions)
            scored.append((distance, pos, candidate))
        scored.sort()
        if (
            len(scored) >= 2
            and scored[0][0] == scored[1][0]
            and scored[0][2] != scored[1][2]
        ):
            return None
        return scored[0][2]

    @staticmethod
    def _candidate_mentions(text: str, candidates: Sequence[str]) -> List[tuple[str, int]]:
        mentions: List[tuple[str, int]] = []
        for candidate in candidates:
            pattern = re.compile(re.escape(candidate) + r"(?:さん|君|ちゃん)?")
            for match in pattern.finditer(text):
                mentions.append((candidate, match.start()))
        mentions.sort(key=lambda item: item[1])
        return mentions

    @staticmethod
    def _extract_reason(text: str) -> str:
        for pattern in _REASON_PATTERNS:
            match = pattern.search(text)
            if match:
                reason = match.group("reason").strip(" \t\r\n、:：")
                return reason if reason else _DEFAULT_REASON

        sentences = re.split(r"(?<=[。.!?！？])", text)
        for sentence in sentences:
            if "ため" in sentence:
                reason = sentence.strip()
                return reason if reason else _DEFAULT_REASON
        return _DEFAULT_REASON

    @classmethod
    def _split_speech_and_reason(cls, text: str) -> tuple[str, str]:
        markers = ("理由としては", "理由は", "なぜなら")
        positions = [(text.find(marker), marker) for marker in markers if text.find(marker) >= 0]
        if not positions:
            return text, cls._extract_reason(text)

        pos, marker = min(positions)
        speech = text[:pos].strip()
        reason = text[pos + len(marker):].strip(" \t\r\n、:：")
        return speech or text, reason or _DEFAULT_REASON

    @staticmethod
    def _dump(payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False)
