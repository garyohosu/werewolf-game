"""Unit/integration tests for GameEngine (SPEC.md 6-13章). Run: python -m unittest discover tests"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from agents import DryRunAgent, PlayerAgent  # noqa: E402
from game_rules import FallbackHandler, GameEngine  # noqa: E402
from json_utils import JsonValidator  # noqa: E402
from log_writer import LogWriter  # noqa: E402
from models import AgentConfig  # noqa: E402
from random_utils import RandomGenerator  # noqa: E402

_PLAYER_NAMES = ["Claude", "Codex", "Grok", "agy"]


def _make_agent_configs() -> List[AgentConfig]:
    return [AgentConfig(name=name, command=name.lower(), args=[], prompt_mode="arg") for name in _PLAYER_NAMES]


class DryRunHappyPathTests(unittest.TestCase):
    def test_full_game_runs_and_produces_valid_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rng = RandomGenerator(42)
            agent = DryRunAgent(rng)
            result, game_dir = _run_game_with_rng(tmp_path, rng, agent)

            self.assertIn(result.executed, _PLAYER_NAMES)
            self.assertIn(result.winner, {"villager", "werewolf"})

            state = json.loads((game_dir / "game_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["phase"], "finished")
            self.assertEqual(set(state["players"].keys()), set(_PLAYER_NAMES))
            roles = [p["role"] for p in state["players"].values()]
            self.assertEqual(sorted(roles), sorted(["werewolf", "seer", "villager", "villager"]))
            self.assertIsNotNone(state["seer_result"])
            self.assertIn(state["seer_result"]["result"], {"werewolf", "human"})
            self.assertEqual(state["executed"], result.executed)
            self.assertEqual(state["winner"], result.winner)

            public_log = (game_dir / "public_log.md").read_text(encoding="utf-8")
            # role list and secret seer result must not leak to public_log.md (17.1章).
            # ("werewolf"/"human" legitimately appear as the winner faction name.)
            self.assertNotIn("役職一覧", public_log)
            self.assertNotIn("占い結果", public_log)
            self.assertNotIn(state["seer_result"]["target"] + "を占い", public_log)

            results_md = (game_dir / "results.md").read_text(encoding="utf-8")
            self.assertIn("役職一覧", results_md)

            # dry-run happy path should not produce any raw/ error files.
            raw_files = list((game_dir / "raw").iterdir())
            self.assertEqual(raw_files, [])

    def test_same_seed_reproduces_same_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            rng1 = RandomGenerator(1234)
            result1, _ = _run_game_with_rng(Path(tmp1), rng1, DryRunAgent(rng1))

            rng2 = RandomGenerator(1234)
            result2, _ = _run_game_with_rng(Path(tmp2), rng2, DryRunAgent(rng2))

            self.assertEqual(result1.executed, result2.executed)
            self.assertEqual(result1.winner, result2.winner)

    def test_winner_matches_executed_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rng = RandomGenerator(7)
            result, game_dir = _run_game_with_rng(Path(tmp), rng, DryRunAgent(rng))
            state = json.loads((game_dir / "game_state.json").read_text(encoding="utf-8"))
            executed_role = state["players"][result.executed]["role"]
            expected_winner = "villager" if executed_role == "werewolf" else "werewolf"
            self.assertEqual(result.winner, expected_winner)


class _BadNightAgent(PlayerAgent):
    """Returns invalid JSON for the night action only, to exercise fallback."""

    def __init__(self, rng: RandomGenerator) -> None:
        self._rng = rng
        self._delegate = DryRunAgent(rng)

    def generate_night_action(self, seer: str, candidates: Sequence[str]) -> str:
        return "this is not valid json"

    def generate_speech(self, player: str, public_log: str) -> str:
        return self._delegate.generate_speech(player, public_log)

    def generate_vote(self, player: str, candidates: Sequence[str], public_log: str) -> str:
        return self._delegate.generate_vote(player, candidates, public_log)


class FallbackTests(unittest.TestCase):
    def test_invalid_night_response_triggers_fallback_and_is_logged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rng = RandomGenerator(99)
            agent = _BadNightAgent(rng)
            result, game_dir = _run_game_with_rng(tmp_path, rng, agent)

            # Game must still complete despite the invalid night response.
            self.assertIn(result.executed, _PLAYER_NAMES)

            state = json.loads((game_dir / "game_state.json").read_text(encoding="utf-8"))
            self.assertIsNotNone(state["seer_result"])
            seer_result = state["seer_result"]
            self.assertNotEqual(seer_result["target"], seer_result["seer"])

            raw_files = list((game_dir / "raw").iterdir())
            self.assertEqual(len(raw_files), 1)
            self.assertTrue(raw_files[0].name.startswith("01_night_"))
            self.assertTrue(raw_files[0].name.endswith("_syntax.txt"))

            results_md = (game_dir / "results.md").read_text(encoding="utf-8")
            self.assertIn("エラー記録", results_md)
            self.assertIn("error_type=syntax", results_md)


class ExecutionDeterminationTests(unittest.TestCase):
    def _engine(self, seed: int) -> GameEngine:
        rng = RandomGenerator(seed)
        return GameEngine(
            agent_configs=_make_agent_configs(),
            rng=rng,
            player_agent=DryRunAgent(rng),
            validator=JsonValidator(),
            fallback_handler=FallbackHandler(rng),
            log_writer=LogWriter(Path(tempfile.mkdtemp()) / "games"),
        )

    def test_single_max_voter_is_executed_without_rng(self) -> None:
        from models import VoteEntry

        engine = self._engine(1)
        votes = [
            VoteEntry(player="Claude", vote="agy", reason="x"),
            VoteEntry(player="Codex", vote="agy", reason="x"),
            VoteEntry(player="Grok", vote="agy", reason="x"),
            VoteEntry(player="agy", vote="Claude", reason="x"),
        ]
        self.assertEqual(engine._determine_execution(votes), "agy")

    def test_tie_is_broken_from_agents_json_order_candidates(self) -> None:
        from models import VoteEntry

        # Claude and Codex tie at 2 votes each; Grok/agy get 0.
        votes = [
            VoteEntry(player="Claude", vote="Codex", reason="x"),
            VoteEntry(player="Codex", vote="Claude", reason="x"),
            VoteEntry(player="Grok", vote="Claude", reason="x"),
            VoteEntry(player="agy", vote="Codex", reason="x"),
        ]
        # Try several seeds; the executed player must always be one of the tied pair.
        for seed in range(10):
            engine = self._engine(seed)
            executed = engine._determine_execution(votes)
            self.assertIn(executed, {"Claude", "Codex"})


def _run_game_with_rng(tmp_path: Path, rng: RandomGenerator, agent: PlayerAgent, game_id: int = 1):
    validator = JsonValidator()
    log_writer = LogWriter(tmp_path / "games")
    engine = GameEngine(
        agent_configs=_make_agent_configs(),
        rng=rng,
        player_agent=agent,
        validator=validator,
        fallback_handler=FallbackHandler(rng),
        log_writer=log_writer,
    )
    result = engine.run_one_game(game_id)
    return result, tmp_path / "games" / f"game_{game_id:04d}"


if __name__ == "__main__":
    unittest.main()
