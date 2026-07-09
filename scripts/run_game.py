#!/usr/bin/env python3
"""Phase 1 dry-run entrypoint.

SPEC.md v0.6-draft 15 chapter. SEQUENCE.md 4 chapter.

    python scripts/run_game.py --games 1 --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents import ConfigLoader, DryRunAgent  # noqa: E402
from game_rules import FallbackHandler, GameEngine  # noqa: E402
from json_utils import JsonValidator  # noqa: E402
from log_writer import LogWriter  # noqa: E402
from models import Mode, RunOptions  # noqa: E402
from random_utils import RandomGenerator  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "agents.json"
LOGS_ROOT = REPO_ROOT / "logs" / "games"


def parse_args(argv: List[str]) -> RunOptions:
    parser = argparse.ArgumentParser(
        prog="run_game.py", description="AI Multi-Agent One Night Werewolf game runner"
    )
    parser.add_argument("--games", type=int, default=1, help="number of games to run (>= 1)")

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", help="run without external AI CLIs (default)")
    mode_group.add_argument(
        "--use-real-agents", action="store_true", help="Phase 3: connect real AI CLIs"
    )

    parser.add_argument("--seed", type=int, default=None, help="random seed for reproducible runs")
    parser.add_argument("--agent-timeout", type=float, default=60.0, help="timeout in seconds for each AI CLI call")

    args = parser.parse_args(argv)

    if args.games < 1:
        parser.error("--games must be a positive integer (1 or greater)")

    mode = Mode.REAL_AGENTS if args.use_real_agents else Mode.DRY_RUN
    return RunOptions(games=args.games, mode=mode, seed=args.seed, agent_timeout=args.agent_timeout)


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    try:
        options = parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    config_loader = ConfigLoader()
    try:
        agent_configs = config_loader.load(CONFIG_PATH)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: failed to load {CONFIG_PATH}: {exc}", file=sys.stderr)
        return 1

    rng = RandomGenerator(options.seed)
    validator = JsonValidator()
    log_writer = LogWriter(LOGS_ROOT)
    fallback_handler = FallbackHandler(rng)

    if options.mode is Mode.DRY_RUN:
        from agents import DryRunAgent
        player_agent = DryRunAgent(rng)
    else:
        from agents import AgentInvoker
        prompts_dir = REPO_ROOT / "prompts"
        player_agent = AgentInvoker(agent_configs, prompts_dir, timeout=options.agent_timeout)

    start_game_id = log_writer.next_start_game_id()

    for i in range(options.games):
        game_id = start_game_id + i
        engine = GameEngine(
            agent_configs=agent_configs,
            rng=rng,
            player_agent=player_agent,
            validator=validator,
            fallback_handler=fallback_handler,
            log_writer=log_writer,
        )
        try:
            result = engine.run_one_game(game_id)
        except OSError as exc:
            print(f"error: failed to write game_{game_id:04d}: {exc}", file=sys.stderr)
            return 1

        print(f"game_{game_id:04d}: executed={result.executed} winner={result.winner}")

    print(f"completed {options.games} game(s). logs: {LOGS_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
