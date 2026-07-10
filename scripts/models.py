"""Data classes and enums shared across the game engine.

SPEC.md v0.6-draft (6, 9, 11, 13, 17.3 chapters), CLASS.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Mode(str, Enum):
    DRY_RUN = "dry_run"
    REAL_AGENTS = "real_agents"


class Role(str, Enum):
    WEREWOLF = "werewolf"
    SEER = "seer"
    VILLAGER = "villager"


class PhaseValue(str, Enum):
    SETUP = "setup"
    NIGHT = "night"
    SPEECH = "speech"
    VOTE = "vote"
    FINISHED = "finished"


@dataclass
class RunOptions:
    games: int
    mode: Mode
    seed: Optional[int]
    agent_timeout: float = 60.0


@dataclass
class AgentConfig:
    name: str
    command: str
    args: List[str]
    prompt_mode: str
    response_mode: str = "json"
    normalize_with: Optional[str] = None


@dataclass
class PlayerState:
    role: Role


@dataclass
class SeerResult:
    seer: str
    target: str
    result: str  # "werewolf" or "human" (SPEC.md 9, 17.3)


@dataclass
class SpeechEntry:
    player: str
    speech: str
    reason: Optional[str]
    failed: bool = False


@dataclass
class VoteEntry:
    player: str
    vote: str
    reason: Optional[str]
    failed: bool = False


@dataclass
class ErrorRecord:
    seq: int
    phase: str
    player: str
    error_type: str


@dataclass
class GameState:
    game_id: int
    phase: PhaseValue
    players: Dict[str, PlayerState] = field(default_factory=dict)
    seer_result: Optional[SeerResult] = None
    executed: Optional[str] = None
    winner: Optional[str] = None


@dataclass
class GameResult:
    game_id: int
    executed: str
    winner: str


@dataclass
class ValidationResult:
    ok: bool
    action: Optional[dict]
    error_type: Optional[str]  # "syntax" | "semantic"
