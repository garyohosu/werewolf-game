import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from agents import DryRunAgent  # noqa: E402
from game_rules import FallbackHandler, GameEngine  # noqa: E402
from json_utils import JsonValidator  # noqa: E402
from log_writer import LogWriter  # noqa: E402
from models import AgentConfig  # noqa: E402
from random_utils import RandomGenerator  # noqa: E402


def test_seed_1234_representative_scenario(tmp_path: Path) -> None:
    names = ["Claude", "Codex", "Grok", "agy"]
    configs = [
        AgentConfig(name=name, command=name.lower(), args=[], prompt_mode="arg")
        for name in names
    ]
    rng = RandomGenerator(1234)
    engine = GameEngine(
        agent_configs=configs,
        rng=rng,
        player_agent=DryRunAgent(rng),
        validator=JsonValidator(),
        fallback_handler=FallbackHandler(rng),
        log_writer=LogWriter(tmp_path / "games"),
    )

    result = engine.run_one_game(1)
    state = json.loads(
        (tmp_path / "games" / "game_0001" / "game_state.json").read_text(encoding="utf-8")
    )

    assert {name: value["role"] for name, value in state["players"].items()} == {
        "Claude": "seer",
        "Codex": "villager",
        "Grok": "werewolf",
        "agy": "villager",
    }
    assert state["seer_result"]["target"] == "Codex"
    assert result.executed == "agy"
    assert result.winner == "werewolf"
