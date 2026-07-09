"""Player agent configuration loading and response generation.

SPEC.md v0.6-draft/v0.7-draft 5, 9, 10, 11, 15.1, 18 chapters.
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Sequence

from models import AgentConfig, Role
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


class AgentTimeoutError(Exception):
    """Timeout expired during CLI agent invocation (Phase 3)."""

    def __init__(self, message: str, stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


class AgentCliError(Exception):
    """CLI agent returned non-zero exit code or execution failed (Phase 3)."""

    def __init__(self, message: str, returncode: int, stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class PlayerAgent(ABC):
    """Common interface for dry-run and real-CLI response generation.

    CLASS.md 3.1: DryRunAgent (Phase 1) and AgentInvoker (Phase 3) both
    implement this interface so GameEngine can depend on it alone.
    """

    @abstractmethod
    def generate_night_action(self, seer: str, candidates: Sequence[str]) -> str:
        ...

    @abstractmethod
    def generate_speech(
        self, player: str, role: Role, public_log: str, seer_result_summary: str = ""
    ) -> str:
        ...

    @abstractmethod
    def generate_vote(
        self,
        player: str,
        role: Role,
        candidates: Sequence[str],
        public_log: str,
        seer_result_summary: str = "",
    ) -> str:
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

    def generate_speech(
        self, player: str, role: Role, public_log: str, seer_result_summary: str = ""
    ) -> str:
        return json.dumps(
            {
                "speech": f"（dry-run）{player}の発言です。",
                "reason": "（dry-run）固定テンプレート発言です。",
            },
            ensure_ascii=False,
        )

    def generate_vote(
        self,
        player: str,
        role: Role,
        candidates: Sequence[str],
        public_log: str,
        seer_result_summary: str = "",
    ) -> str:
        target = self._rng.choice(candidates)
        return json.dumps(
            {"vote": target, "reason": "（dry-run）シード付き乱数で選択しました。"},
            ensure_ascii=False,
        )


class AgentInvoker(PlayerAgent):
    """Phase 3 real-CLI response generator."""

    def __init__(
        self,
        agent_configs: Sequence[AgentConfig],
        prompts_dir: Path,
        timeout: float = 60.0,
    ) -> None:
        self._configs = {config.name: config for config in agent_configs}
        player_names = [config.name for config in agent_configs]
        self._prompt_builder = PromptBuilder(prompts_dir, player_names)
        self._timeout = timeout
        self.warnings: List[str] = []

    def pop_warnings(self) -> List[str]:
        w = list(self.warnings)
        self.warnings.clear()
        return w

    def generate_night_action(self, seer: str, candidates: Sequence[str]) -> str:
        prompt = self._prompt_builder.build_night_prompt(seer, candidates)
        return self._invoke(seer, prompt)

    def generate_speech(
        self, player: str, role: Role, public_log: str, seer_result_summary: str = ""
    ) -> str:
        prompt = self._prompt_builder.build_speech_prompt(player, role, public_log, seer_result_summary)
        return self._invoke(player, prompt)

    def generate_vote(
        self,
        player: str,
        role: Role,
        candidates: Sequence[str],
        public_log: str,
        seer_result_summary: str = "",
    ) -> str:
        prompt = self._prompt_builder.build_vote_prompt(player, role, candidates, public_log, seer_result_summary)
        return self._invoke(player, prompt)

    def _invoke(self, player: str, prompt: str) -> str:
        import subprocess
        import tempfile

        config = self._configs[player]
        cmd = [config.command] + config.args

        stdin_input = None
        if config.prompt_mode == "arg":
            cmd.append(prompt)
        elif config.prompt_mode == "stdin":
            stdin_input = prompt

        temp_dir = tempfile.TemporaryDirectory()
        try:
            cwd = temp_dir.name
            try:
                res = subprocess.run(
                    cmd,
                    input=stdin_input,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    shell=False,
                    cwd=cwd,
                    timeout=self._timeout,
                )
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                raise AgentTimeoutError(
                    f"{player}: CLI execution timed out after {self._timeout}s",
                    stdout=stdout,
                    stderr=stderr,
                ) from exc
            except FileNotFoundError as exc:
                raise AgentCliError(
                    f"{player}: CLI command not found: {config.command}",
                    returncode=127,
                    stdout="",
                    stderr=str(exc),
                ) from exc
            except Exception as exc:
                raise AgentCliError(
                    f"{player}: CLI execution failed: {exc}",
                    returncode=-1,
                    stdout="",
                    stderr=str(exc),
                ) from exc

            if res.returncode != 0:
                raise AgentCliError(
                    f"{player}: CLI returned non-zero exit code {res.returncode}",
                    returncode=res.returncode,
                    stdout=res.stdout or "",
                    stderr=res.stderr or "",
                )

            return res.stdout or ""
        finally:
            try:
                temp_dir.cleanup()
            except Exception as exc:
                self.warnings.append(
                    f"Warning: Failed to delete temporary directory {temp_dir.name}: {exc}"
                )


_ROLE_PROMPT_FILES: Dict[Role, str] = {
    Role.VILLAGER: "villager_prompt.md",
    Role.SEER: "seer_prompt.md",
    Role.WEREWOLF: "werewolf_prompt.md",
}

# Matches the fenced ```text block under the "## 本文" heading in each
# prompts/*.md file (see prompts/common_player_prompt.md for the format).
_BODY_BLOCK_PATTERN = re.compile(r"## 本文\s*\n\s*```text\n(.*?)\n```", re.DOTALL)

_PLACEHOLDER_PATTERN = re.compile(r"\{\{[a-z_]+\}\}")


class PromptBuilder:
    """Assembles the actual prompt text sent to an AI player from prompts/*.md.

    CLASS.md 3章: used by AgentInvoker (Phase 3). Concatenates
    common_player_prompt.md + role prompt + phase prompt, in that order, and
    substitutes {{...}} placeholders (SPEC.md v0.7-draft 改訂履歴, prompts/*.md).
    """

    def __init__(self, prompts_dir: Path, player_names: Sequence[str]) -> None:
        self._player_list_text = "、".join(player_names)
        self._common_template = self._load_template(prompts_dir / "common_player_prompt.md")
        self._role_templates: Dict[Role, str] = {
            role: self._load_template(prompts_dir / filename)
            for role, filename in _ROLE_PROMPT_FILES.items()
        }
        self._night_seer_template = self._load_template(prompts_dir / "night_seer_prompt.md")
        self._speech_template = self._load_template(prompts_dir / "speech_prompt.md")
        self._vote_template = self._load_template(prompts_dir / "vote_prompt.md")

    def build_night_prompt(self, seer: str, candidates: Sequence[str]) -> str:
        """夜フェーズ: 占い師の占いプロンプト（占い師以外は夜に行動しないため役職固定）。"""
        phase_text = self._render(
            self._night_seer_template, player_name=seer, candidates="、".join(candidates)
        )
        return self._assemble(seer, Role.SEER, phase_text)

    def build_speech_prompt(
        self, player: str, role: Role, public_log: str, seer_result_summary: str = ""
    ) -> str:
        phase_text = self._render(
            self._speech_template,
            player_name=player,
            public_log=public_log,
            seer_result_summary=seer_result_summary,
        )
        return self._assemble(player, role, phase_text)

    def build_vote_prompt(
        self,
        player: str,
        role: Role,
        candidates: Sequence[str],
        public_log: str,
        seer_result_summary: str = "",
    ) -> str:
        phase_text = self._render(
            self._vote_template,
            player_name=player,
            public_log=public_log,
            candidates="、".join(candidates),
            seer_result_summary=seer_result_summary,
        )
        return self._assemble(player, role, phase_text)

    def _assemble(self, player: str, role: Role, phase_text: str) -> str:
        common_text = self._render(self._common_template, player_name=player)
        role_text = self._render(self._role_templates[role], player_name=player)
        prompt = "\n\n".join([common_text, role_text, phase_text])

        leftover = _PLACEHOLDER_PATTERN.search(prompt)
        if leftover:
            raise ValueError(f"unresolved placeholder {leftover.group(0)!r} in assembled prompt")
        return prompt

    def _render(self, template: str, **values: str) -> str:
        text = template.replace("{{player_list}}", self._player_list_text)
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        return text

    @staticmethod
    def _load_template(path: Path) -> str:
        content = path.read_text(encoding="utf-8")
        match = _BODY_BLOCK_PATTERN.search(content)
        if not match:
            raise ValueError(f"{path}: could not find a '## 本文' text block")
        return match.group(1)
