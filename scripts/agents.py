"""Player agent configuration loading and response generation.

SPEC.md v0.6-draft 5, 9, 10, 11, 15.1, 18 chapters.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Sequence

from models import AgentConfig
from random_utils import RandomGenerator


class ConfigLoader:
    """Loads config/agents.json, preserving player definition order (5章)."""

    def load(self, path: Path) -> List[AgentConfig]:
        def reject_duplicate_names(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"{path}: duplicate player name: {key}")
                result[key] = value
            return result

        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f, object_pairs_hook=reject_duplicate_names)
        if not isinstance(raw, dict) or len(raw) != 4:
            raise ValueError(f"{path} must contain exactly four uniquely named players")

        configs: List[AgentConfig] = []
        for name, entry in raw.items():
            if not isinstance(name, str) or not name:
                raise ValueError("player names must be non-empty strings")
            if not isinstance(entry, dict):
                raise ValueError(f"{name}: configuration must be an object")
            if set(entry) != {"command", "args", "prompt_mode"}:
                raise ValueError(f"{name}: command, args, and prompt_mode are required")
            command = entry["command"]
            args = entry["args"]
            prompt_mode = entry["prompt_mode"]
            if not isinstance(command, str) or not command:
                raise ValueError(f"{name}: command must be a non-empty string")
            if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
                raise ValueError(f"{name}: args must be an array of strings")
            if prompt_mode not in {"arg", "stdin"}:
                raise ValueError(f"{name}: prompt_mode must be 'arg' or 'stdin'")
            configs.append(
                AgentConfig(name=name, command=command, args=list(args), prompt_mode=prompt_mode)
            )
        return configs


class PlayerAgent(ABC):
    """Common interface for dry-run and real-CLI response generation.

    CLASS.md 3.1: DryRunAgent (Phase 1) and AgentInvoker (Phase 3) both
    implement this interface so GameEngine can depend on it alone.
    """

    @abstractmethod
    def generate_night_action(self, seer: str, candidates: Sequence[str]) -> str:
        ...

    @abstractmethod
    def generate_speech(self, player: str, public_log: str) -> str:
        ...

    @abstractmethod
    def generate_vote(self, player: str, candidates: Sequence[str], public_log: str) -> str:
        ...


class DryRunAgent(PlayerAgent):
    """Phase 1 dry-run response generator (SPEC.md 15.1章)."""

    def __init__(self, rng: RandomGenerator) -> None:
        self._rng = rng

    def generate_night_action(self, seer: str, candidates: Sequence[str]) -> str:
        target = self._rng.choice(candidates)
        return json.dumps(
            {"target": target, "reason": "（dry-run）シード付き乱数で選択しました。"},
            ensure_ascii=False,
        )

    def generate_speech(self, player: str, public_log: str) -> str:
        return json.dumps(
            {
                "speech": f"（dry-run）{player}の発言です。",
                "reason": "（dry-run）固定テンプレート発言です。",
            },
            ensure_ascii=False,
        )

    def generate_vote(self, player: str, candidates: Sequence[str], public_log: str) -> str:
        target = self._rng.choice(candidates)
        return json.dumps(
            {"vote": target, "reason": "（dry-run）シード付き乱数で選択しました。"},
            ensure_ascii=False,
        )


class AgentInvoker(PlayerAgent):
    """Phase 3 real-CLI response generator.

    Not implemented in Phase 1 (SPEC.md 20章 Phase 3). run_game.py rejects
    --use-real-agents before this class would ever be constructed; it exists
    here so the PlayerAgent interface and CLASS.md design are already in
    place for Phase 3.
    """

    def __init__(self, agent_config: AgentConfig) -> None:
        self._agent_config = agent_config

    def generate_night_action(self, seer: str, candidates: Sequence[str]) -> str:
        raise NotImplementedError("Phase 3 (real-agents) is not implemented yet")

    def generate_speech(self, player: str, public_log: str) -> str:
        raise NotImplementedError("Phase 3 (real-agents) is not implemented yet")

    def generate_vote(self, player: str, candidates: Sequence[str], public_log: str) -> str:
        raise NotImplementedError("Phase 3 (real-agents) is not implemented yet")
