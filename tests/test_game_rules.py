"""Unit/integration tests for GameEngine (SPEC.md 6-13章). Run: python -m unittest discover tests"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List, Sequence
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from agents import AgentCliError, AgentInvoker, AgentTimeoutError, DryRunAgent, PlayerAgent  # noqa: E402
from game_rules import FallbackHandler, GameEngine  # noqa: E402
from json_utils import JsonValidator  # noqa: E402
from log_writer import LogWriter  # noqa: E402
from models import AgentConfig, Role  # noqa: E402
from random_utils import RandomGenerator  # noqa: E402

_PLAYER_NAMES = ["Claude", "Codex", "Grok", "agy"]
REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_PROMPTS_DIR = REPO_ROOT / "prompts"


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
            for filename in ("game_state.json", "public_log.md", "results.md"):
                self.assertFalse((tmp_path / filename).exists())

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

    def generate_speech(
        self, player: str, role: Role, public_log: str, seer_result_summary: str = ""
    ) -> str:
        return self._delegate.generate_speech(player, role, public_log, seer_result_summary)

    def generate_vote(
        self,
        player: str,
        role: Role,
        candidates: Sequence[str],
        public_log: str,
        seer_result_summary: str = "",
    ) -> str:
        return self._delegate.generate_vote(player, role, candidates, public_log, seer_result_summary)


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


class _TimeoutOnNightAgent(PlayerAgent):
    """Raises AgentTimeoutError for the night action only (Phase 3 fallback path)."""

    def __init__(self, rng: RandomGenerator) -> None:
        self._delegate = DryRunAgent(rng)

    def generate_night_action(self, seer: str, candidates: Sequence[str]) -> str:
        raise AgentTimeoutError(f"{seer}: CLI execution timed out after 60.0s", stdout="", stderr="")

    def generate_speech(
        self, player: str, role: Role, public_log: str, seer_result_summary: str = ""
    ) -> str:
        return self._delegate.generate_speech(player, role, public_log, seer_result_summary)

    def generate_vote(
        self,
        player: str,
        role: Role,
        candidates: Sequence[str],
        public_log: str,
        seer_result_summary: str = "",
    ) -> str:
        return self._delegate.generate_vote(player, role, candidates, public_log, seer_result_summary)


class _CliErrorOnVoteAgent(PlayerAgent):
    """Raises AgentCliError for every vote call (Phase 3 fallback path)."""

    def __init__(self, rng: RandomGenerator) -> None:
        self._delegate = DryRunAgent(rng)

    def generate_night_action(self, seer: str, candidates: Sequence[str]) -> str:
        return self._delegate.generate_night_action(seer, candidates)

    def generate_speech(
        self, player: str, role: Role, public_log: str, seer_result_summary: str = ""
    ) -> str:
        return self._delegate.generate_speech(player, role, public_log, seer_result_summary)

    def generate_vote(
        self,
        player: str,
        role: Role,
        candidates: Sequence[str],
        public_log: str,
        seer_result_summary: str = "",
    ) -> str:
        raise AgentCliError(
            f"{player}: CLI returned non-zero exit code 1", returncode=1, stdout="", stderr="boom"
        )


class _CodexNaturalTextAgent(PlayerAgent):
    def __init__(self, rng: RandomGenerator) -> None:
        self._delegate = DryRunAgent(rng)

    def generate_night_action(self, seer: str, candidates: Sequence[str]) -> str:
        if seer == "Codex":
            return "Grokを占います。理由は発言の色を確認したいためです。"
        return self._delegate.generate_night_action(seer, candidates)

    def generate_speech(
        self, player: str, role: Role, public_log: str, seer_result_summary: str = ""
    ) -> str:
        if player == "Codex":
            return "私は村人として慎重に見ます。理由は、占い師を無理に出したくないためです。"
        return self._delegate.generate_speech(player, role, public_log, seer_result_summary)

    def generate_vote(
        self,
        player: str,
        role: Role,
        candidates: Sequence[str],
        public_log: str,
        seer_result_summary: str = "",
    ) -> str:
        if player == "Codex":
            return "Claudeに投票します。理由は占い師を炙っているように見えるためです。"
        return self._delegate.generate_vote(player, role, candidates, public_log, seer_result_summary)


class Phase3ExceptionFallbackTests(unittest.TestCase):
    """GameEngine must route AgentTimeoutError/AgentCliError through the same
    raw/-save + FallbackHandler path as JSON syntax/semantic errors (CLASS.md 3.5)."""

    def test_agent_timeout_error_during_night_triggers_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rng = RandomGenerator(11)
            result, game_dir = _run_game_with_rng(tmp_path, rng, _TimeoutOnNightAgent(rng))

            self.assertIn(result.executed, _PLAYER_NAMES)

            state = json.loads((game_dir / "game_state.json").read_text(encoding="utf-8"))
            self.assertIsNotNone(state["seer_result"])

            raw_files = list((game_dir / "raw").iterdir())
            self.assertEqual(len(raw_files), 1)
            self.assertTrue(raw_files[0].name.endswith("_timeout.txt"))
            self.assertTrue(raw_files[0].name.startswith("01_night_"))

            results_md = (game_dir / "results.md").read_text(encoding="utf-8")
            self.assertIn("error_type=timeout", results_md)

    def test_agent_cli_error_during_vote_triggers_fallback_for_all_players(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rng = RandomGenerator(23)
            result, game_dir = _run_game_with_rng(tmp_path, rng, _CliErrorOnVoteAgent(rng))

            # Every player's vote fails -> 4 raw/ files, one per player, all "cli".
            self.assertIn(result.executed, _PLAYER_NAMES)
            raw_files = sorted(p.name for p in (game_dir / "raw").iterdir())
            self.assertEqual(len(raw_files), 4)
            for name in raw_files:
                self.assertTrue(name.endswith("_vote_" + name.split("_vote_")[1]))
                self.assertTrue(name.endswith("_cli.txt"))

            results_md = (game_dir / "results.md").read_text(encoding="utf-8")
            self.assertEqual(results_md.count("error_type=cli"), 4)


class NaturalTextModeTests(unittest.TestCase):
    def test_codex_natural_text_is_normalized_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rng = RandomGenerator(42)
            configs = _make_agent_configs()
            for config in configs:
                if config.name == "Codex":
                    config.response_mode = "natural_text"
                    config.normalize_with = "local"

            log_writer = LogWriter(tmp_path / "games")
            engine = GameEngine(
                agent_configs=configs,
                rng=rng,
                player_agent=_CodexNaturalTextAgent(rng),
                validator=JsonValidator(),
                fallback_handler=FallbackHandler(rng),
                log_writer=log_writer,
            )
            engine.run_one_game(1)

            game_dir = tmp_path / "games" / "game_0001"
            raw_names = sorted(p.name for p in (game_dir / "raw").iterdir())
            self.assertTrue(any(name.endswith("_speech_Codex_natural.txt") for name in raw_names))
            self.assertTrue(any(name.endswith("_speech_Codex_normalized.json") for name in raw_names))
            self.assertTrue(any(name.endswith("_vote_Codex_natural.txt") for name in raw_names))
            self.assertTrue(any(name.endswith("_vote_Codex_normalized.json") for name in raw_names))

            public_log = (game_dir / "public_log.md").read_text(encoding="utf-8")
            self.assertIn("私は村人として慎重に見ます。", public_log)

            results_md = (game_dir / "results.md").read_text(encoding="utf-8")
            self.assertNotIn("player=Codex error_type=normalize", results_md)
            self.assertNotIn("Codex (失敗)", results_md)


def _fake_subprocess_run(*args, **kwargs):
    """Simulates a well-behaved external AI CLI: parses the assembled prompt
    (passed as the last argv element, since these tests use prompt_mode=arg)
    well enough to return schema-valid JSON for whichever phase was asked."""
    import re

    cmd = args[0]
    prompt = cmd[-1]

    result = MagicMock()
    result.returncode = 0
    result.stderr = ""

    if "夜フェーズです" in prompt:
        m = re.search(r"占うことができるプレイヤー: ([^\n]+)", prompt)
        target = m.group(1).split("、")[0]
        result.stdout = json.dumps({"target": target, "reason": "real-cli stub"})
    elif "発言ラウンドです" in prompt:
        result.stdout = json.dumps({"speech": "hello from real-cli stub", "reason": "real-cli stub"})
    elif "投票ラウンドです" in prompt:
        m = re.search(r"投票できるプレイヤー: ([^\n]+)", prompt)
        target = m.group(1).split("、")[0]
        result.stdout = json.dumps({"vote": target, "reason": "real-cli stub"})
    else:
        raise AssertionError(f"unrecognized prompt phase in: {prompt[:200]!r}")

    return result


class AgentInvokerGameEngineIntegrationTests(unittest.TestCase):
    """Runs a full game through the real AgentInvoker (Phase 3) with
    subprocess.run mocked, so no actual CLI is required (per Phase 3 E2E
    policy: unit/integration tests mock subprocess; real CLIs are optional
    manual verification)."""

    def test_full_game_via_agent_invoker_with_valid_stdout(self) -> None:
        agent_configs = [
            AgentConfig(name=name, command=name.lower(), args=["-p"], prompt_mode="arg")
            for name in _PLAYER_NAMES
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rng = RandomGenerator(5)
            invoker = AgentInvoker(agent_configs, REAL_PROMPTS_DIR, timeout=30.0)
            log_writer = LogWriter(tmp_path / "games")
            engine = GameEngine(
                agent_configs=agent_configs,
                rng=rng,
                player_agent=invoker,
                validator=JsonValidator(),
                fallback_handler=FallbackHandler(rng),
                log_writer=log_writer,
            )

            with patch("subprocess.run", side_effect=_fake_subprocess_run) as mock_run:
                result = engine.run_one_game(1)

            self.assertIn(result.executed, _PLAYER_NAMES)
            self.assertIn(result.winner, {"villager", "werewolf"})

            # 1 night + 4 speech + 4 vote = 9 CLI invocations, all via subprocess.run.
            self.assertEqual(mock_run.call_count, 9)
            for _, kwargs in mock_run.call_args_list:
                self.assertIs(kwargs["shell"], False)
                self.assertNotEqual(Path(kwargs["cwd"]), REPO_ROOT)

            game_dir = tmp_path / "games" / "game_0001"
            raw_files = list((game_dir / "raw").iterdir())
            self.assertEqual(raw_files, [], "well-behaved stdout must not produce raw/ error files")

            results_md = (game_dir / "results.md").read_text(encoding="utf-8")
            self.assertNotIn("エラー記録", results_md)
            for filename in ("game_state.json", "public_log.md", "results.md"):
                self.assertFalse((tmp_path / filename).exists())


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
