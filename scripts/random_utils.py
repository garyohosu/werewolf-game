"""Single shared random generator wrapper.

SPEC.md v0.6-draft 16.5 chapter: a single random.Random instance is created
once per run_game.py invocation and consumed in a fixed order for the whole
run (including across --games N games).
"""
from __future__ import annotations

import random
from typing import List, Optional, Sequence, TypeVar

T = TypeVar("T")


class RandomGenerator:
    """Wraps a single random.Random instance created once per run."""

    def __init__(self, seed: Optional[int] = None) -> None:
        self._rng = random.Random(seed)

    def shuffle_roles(self, roles: List[T]) -> List[T]:
        shuffled = list(roles)
        self._rng.shuffle(shuffled)
        return shuffled

    def choice(self, candidates: Sequence[T]) -> T:
        return self._rng.choice(list(candidates))
