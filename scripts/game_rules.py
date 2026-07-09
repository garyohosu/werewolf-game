"""Game engine: role assignment, night/day phases, execution, and winner rules.

SPEC.md v0.6-draft 6-13 chapters. SEQUENCE.md 4, 6, 7 chapters. CLASS.md.
"""
from __future__ import annotations

from typing import Dict, List, Sequence

from agents import PlayerAgent
from json_utils import JsonValidator
from log_writer import LogWriter
from models import (
    AgentConfig,
    GameResult,
    GameState,
    PhaseValue,
    PlayerState,
    Role,
    SeerResult,
    SpeechEntry,
    VoteEntry,
)
from random_utils import RandomGenerator

# 6章: 人狼1・占い師1・村人2
_ROLE_POOL: List[Role] = [Role.WEREWOLF, Role.SEER, Role.VILLAGER, Role.VILLAGER]


class FallbackHandler:
    """Determines fallback actions when a response fails validation (12.3章)."""

    def __init__(self, rng: RandomGenerator) -> None:
        self._rng = rng

    def decide_speech(self) -> str:
        # 発言失敗はランダム選出しない（12.3章）。
        return "発言に失敗しました。"

    def decide_target(self, candidates: Sequence[str]) -> str:
        return self._rng.choice(candidates)


class GameEngine:
    """Runs a single One Night Werewolf game from role assignment to results."""

    def __init__(
        self,
        agent_configs: List[AgentConfig],
        rng: RandomGenerator,
        player_agent: PlayerAgent,
        validator: JsonValidator,
        fallback_handler: FallbackHandler,
        log_writer: LogWriter,
    ) -> None:
        self._player_names = [config.name for config in agent_configs]
        self._rng = rng
        self._agent = player_agent
        self._validator = validator
        self._fallback = fallback_handler
        self._log = log_writer
        self._error_seq = 0

    def run_one_game(self, game_id: int) -> GameResult:
        state = GameState(game_id=game_id, phase=PhaseValue.SETUP)

        self._log.create_game_dir(game_id)
        self._log.init_public_log(game_id)
        self._log.init_results(game_id)
        self._log.save_game_state(game_id, state)

        self._assign_roles(state)
        state.phase = PhaseValue.NIGHT
        self._log.save_game_state(game_id, state)

        self._run_night_phase(game_id, state)
        state.phase = PhaseValue.SPEECH
        self._log.save_game_state(game_id, state)

        speeches = self._run_speech_round(game_id, state)
        state.phase = PhaseValue.VOTE
        self._log.save_game_state(game_id, state)

        votes = self._run_vote_round(game_id, speeches)

        executed = self._determine_execution(votes)
        winner = self._determine_winner(state, executed)
        state.executed = executed
        state.winner = winner
        state.phase = PhaseValue.FINISHED
        self._log.save_game_state(game_id, state)
        self._log.append_execution_result(game_id, executed, winner)
        self._log.save_results(game_id, state, speeches, votes)

        return GameResult(game_id=game_id, executed=executed, winner=winner)

    def _next_seq(self) -> int:
        self._error_seq += 1
        return self._error_seq

    def _assign_roles(self, state: GameState) -> None:
        shuffled = self._rng.shuffle_roles(list(_ROLE_POOL))
        for name, role in zip(self._player_names, shuffled):
            state.players[name] = PlayerState(role=role)

    def _run_night_phase(self, game_id: int, state: GameState) -> None:
        seer = next(name for name, player in state.players.items() if player.role == Role.SEER)
        candidates = [name for name in self._player_names if name != seer]

        raw = self._agent.generate_night_action(seer, candidates)
        result = self._validator.validate(raw, "night", seer, candidates)

        if result.ok:
            target = result.action["target"]
        else:
            seq = self._next_seq()
            self._log.save_raw_response(game_id, seq, "night", seer, result.error_type, raw)
            self._log.record_error(game_id, seq, "night", seer, result.error_type)
            target = self._fallback.decide_target(candidates)

        role = state.players[target].role
        seer_result_value = "werewolf" if role == Role.WEREWOLF else "human"
        state.seer_result = SeerResult(seer=seer, target=target, result=seer_result_value)

    def _run_speech_round(self, game_id: int, state: GameState) -> List[SpeechEntry]:
        speeches: List[SpeechEntry] = []
        for player in self._player_names:
            public_log_so_far = "\n".join(f"{e.player}: {e.speech}" for e in speeches)
            raw = self._agent.generate_speech(player, public_log_so_far)
            result = self._validator.validate(raw, "speech", player, [])

            if result.ok:
                entry = SpeechEntry(
                    player=player, speech=result.action["speech"], reason=result.action["reason"]
                )
            else:
                seq = self._next_seq()
                self._log.save_raw_response(game_id, seq, "speech", player, result.error_type, raw)
                self._log.record_error(game_id, seq, "speech", player, result.error_type)
                entry = SpeechEntry(
                    player=player, speech=self._fallback.decide_speech(), reason=None, failed=True
                )

            speeches.append(entry)
            self._log.append_speech(game_id, entry)

        return speeches

    def _run_vote_round(self, game_id: int, speeches: List[SpeechEntry]) -> List[VoteEntry]:
        # 発言ラウンド終了時点の公開ログのスナップショットを全員に渡す（10.2章）。
        frozen_public_log = "\n".join(f"{e.player}: {e.speech}" for e in speeches)
        votes: List[VoteEntry] = []

        for player in self._player_names:
            candidates = [name for name in self._player_names if name != player]
            raw = self._agent.generate_vote(player, candidates, frozen_public_log)
            result = self._validator.validate(raw, "vote", player, candidates)

            if result.ok:
                entry = VoteEntry(
                    player=player, vote=result.action["vote"], reason=result.action["reason"]
                )
            else:
                seq = self._next_seq()
                self._log.save_raw_response(game_id, seq, "vote", player, result.error_type, raw)
                self._log.record_error(game_id, seq, "vote", player, result.error_type)
                entry = VoteEntry(
                    player=player, vote=self._fallback.decide_target(candidates), reason=None, failed=True
                )

            votes.append(entry)

        # 全員分を内部収集してから一括公開する（10.2章）。
        self._log.append_votes(game_id, votes)
        return votes

    def _determine_execution(self, votes: List[VoteEntry]) -> str:
        tally: Dict[str, int] = {}
        for vote in votes:
            tally[vote.vote] = tally.get(vote.vote, 0) + 1

        max_count = max(tally.values())
        # config/agents.json定義順に並べてから同票候補を抽出する（13, 16.5章）。
        tied = [name for name in self._player_names if tally.get(name, 0) == max_count]

        if len(tied) == 1:
            return tied[0]
        return self._rng.choice(tied)

    @staticmethod
    def _determine_winner(state: GameState, executed: str) -> str:
        role = state.players[executed].role
        return "villager" if role == Role.WEREWOLF else "werewolf"
