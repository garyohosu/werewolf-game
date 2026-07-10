"""Probe Codex CLI behavior for werewolf-player JSON prompts.

This script is intentionally separate from the game runner. It calls Codex CLI
with small prompts and records whether stdout matches the expected game schema.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence


REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_ROOT = REPO_ROOT / "logs" / "codex_probe"
CODEX_COMMAND = "codex.cmd"
CODEX_BASE_ARGS = ["exec", "--skip-git-repo-check"]
STDERR_PREVIEW_CHARS = 2000


PROMPTS: Dict[str, str] = {
    "simple_speech": """JSON ONLY.
Return exactly one JSON object:
{"speech":"テスト","reason":"確認"}
Do not return ok/status/message.
""",
    "compact_speech": """JSON ONLY.
Player: Codex
Phase: speech
Role: villager
Players: Claude, Codex, Grok, agy
Public log:
- Claude: 私は村人です。占い師がいれば結果を聞きたいです。
- Grok: Claudeの発言は協力的ですが、占い師を炙り出している可能性もあります。

Return exactly one JSON object:
{"speech":"...","reason":"..."}

The speech value must be Codex's statement in the werewolf game.
The reason value must explain why Codex says it.
Do not return ok/status/acknowledged/message.
Do not ask questions.
""",
    "compact_vote": """JSON ONLY.
Player: Codex
Phase: vote
Role: villager
Candidates: Claude, Grok, agy
Public log:
- Claude: 私は村人です。占い師がいれば結果を聞きたいです。
- Grok: Claudeの発言は占い師を炙り出している可能性があります。
- agy: Codexの発言がないのは少し気になります。

Return exactly one JSON object:
{"vote":"...","reason":"..."}

The vote value must be exactly one of: Claude, Grok, agy.
Do not return ok/status/acknowledged/message.
Do not ask questions.
""",
    "compact_night": """JSON ONLY.
Player: Codex
Phase: night
Role: seer
Candidates: Claude, Grok, agy

Return exactly one JSON object:
{"target":"...","reason":"..."}

The target value must be exactly one of: Claude, Grok, agy.
Do not return ok/status/acknowledged/message.
Do not ask questions.
""",
    "natural_speech": """あなたはAI版ワンナイト人狼ゲームのプレイヤー Codex です。
JSONではなく、普通の日本語の文章で答えてください。
追加質問はしないでください。

フェーズ: 発言
役職: 村人
プレイヤー: Claude, Codex, Grok, agy
公開ログ:
- Claude: 私は村人です。占い師がいれば結果を聞きたいです。
- Grok: Claudeの発言は協力的ですが、占い師を炙り出している可能性もあります。

自分の発言と、その理由を書いてください。
""",
}


CASE_PHASE: Dict[str, str] = {
    "simple_speech": "speech",
    "compact_speech": "speech",
    "compact_vote": "vote",
    "compact_night": "night",
    "natural_speech": "natural",
}


CANDIDATES = ["Claude", "Grok", "agy"]


@dataclass
class ValidationOutcome:
    json_parsed: bool
    schema_ok: bool
    error_type: Optional[str]
    parsed: Optional[dict]
    message: str


@dataclass
class ProbeResult:
    case: str
    model: Optional[str]
    prompt_mode: str
    command: List[str]
    returncode: int
    stdout: str
    stderr_preview: str
    json_parsed: bool
    schema_ok: bool
    error_type: Optional[str]
    validation_message: str
    log_dir: str


def validate_stdout(stdout: str, case_name: str) -> ValidationOutcome:
    phase = CASE_PHASE[case_name]
    if phase == "natural":
        ok = bool(stdout.strip())
        return ValidationOutcome(
            json_parsed=False,
            schema_ok=ok,
            error_type=None if ok else "syntax",
            parsed=None,
            message="non-empty natural text" if ok else "empty natural text",
        )

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return ValidationOutcome(
            json_parsed=False,
            schema_ok=False,
            error_type="syntax",
            parsed=None,
            message=f"JSON parse failed: {exc}",
        )

    if not isinstance(parsed, dict):
        return ValidationOutcome(
            json_parsed=True,
            schema_ok=False,
            error_type="semantic",
            parsed=None,
            message="parsed JSON is not an object",
        )

    expected_keys = {
        "speech": {"speech", "reason"},
        "vote": {"vote", "reason"},
        "night": {"target", "reason"},
    }[phase]
    actual_keys = set(parsed)
    if actual_keys != expected_keys:
        return ValidationOutcome(
            json_parsed=True,
            schema_ok=False,
            error_type="semantic",
            parsed=parsed,
            message=f"expected keys {sorted(expected_keys)}, got {sorted(actual_keys)}",
        )

    for key in expected_keys:
        if not isinstance(parsed[key], str) or not parsed[key].strip():
            return ValidationOutcome(
                json_parsed=True,
                schema_ok=False,
                error_type="semantic",
                parsed=parsed,
                message=f"{key!r} must be a non-empty string",
            )

    if phase == "vote" and parsed["vote"] not in CANDIDATES:
        return ValidationOutcome(
            json_parsed=True,
            schema_ok=False,
            error_type="semantic",
            parsed=parsed,
            message=f"vote must be one of {CANDIDATES}",
        )
    if phase == "night" and parsed["target"] not in CANDIDATES:
        return ValidationOutcome(
            json_parsed=True,
            schema_ok=False,
            error_type="semantic",
            parsed=parsed,
            message=f"target must be one of {CANDIDATES}",
        )

    return ValidationOutcome(
        json_parsed=True,
        schema_ok=True,
        error_type=None,
        parsed=parsed,
        message="ok",
    )


def build_command(model: Optional[str], prompt_mode: str, prompt: str) -> List[str]:
    cmd = [CODEX_COMMAND] + CODEX_BASE_ARGS
    if model:
        cmd.extend(["--model", model])
    if prompt_mode == "arg":
        cmd.append(prompt)
    return cmd


def run_probe(case_name: str, prompt_mode: str, model: Optional[str], timeout: float) -> ProbeResult:
    prompt = PROMPTS[case_name]
    cmd = build_command(model, prompt_mode, prompt)
    stdin_input = prompt if prompt_mode == "stdin" else None
    run_dir = make_run_dir()

    res = subprocess.run(
        cmd,
        input=stdin_input,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        cwd=REPO_ROOT,
        timeout=timeout,
    )

    stdout = res.stdout or ""
    stderr = res.stderr or ""
    validation = validate_stdout(stdout, case_name)
    result = ProbeResult(
        case=case_name,
        model=model,
        prompt_mode=prompt_mode,
        command=cmd[:-1] + ["<prompt>"] if prompt_mode == "arg" else cmd,
        returncode=res.returncode,
        stdout=stdout,
        stderr_preview=stderr[:STDERR_PREVIEW_CHARS],
        json_parsed=validation.json_parsed,
        schema_ok=validation.schema_ok,
        error_type=validation.error_type,
        validation_message=validation.message,
        log_dir=str(run_dir),
    )
    write_logs(run_dir, prompt, stdout, stderr, result, validation)
    return result


def make_run_dir() -> Path:
    base = LOG_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = base
    suffix = 2
    while run_dir.exists():
        run_dir = Path(f"{base}_{suffix}")
        suffix += 1
    run_dir.mkdir(parents=True)
    return run_dir


def write_logs(
    run_dir: Path,
    prompt: str,
    stdout: str,
    stderr: str,
    result: ProbeResult,
    validation: ValidationOutcome,
) -> None:
    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    (run_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
    (run_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    payload = asdict(result)
    payload["parsed"] = validation.parsed
    (run_dir / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def print_result(result: ProbeResult) -> None:
    print(f"case: {result.case}")
    print(f"model: {result.model or '(default)'}")
    print(f"prompt_mode: {result.prompt_mode}")
    print(f"returncode: {result.returncode}")
    print("stdout:")
    print(result.stdout)
    print("stderr_preview:")
    print(result.stderr_preview)
    print(f"json_parsed: {result.json_parsed}")
    print(f"schema_ok: {result.schema_ok}")
    print(f"error_type: {result.error_type}")
    print(f"validation_message: {result.validation_message}")
    print(f"log_dir: {result.log_dir}")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=sorted(PROMPTS), default="simple_speech")
    parser.add_argument("--prompt-mode", choices=["arg", "stdin"], default="arg")
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-calls", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.max_calls < 1:
        raise SystemExit("--max-calls must be at least 1")

    planned_calls = 1
    if planned_calls > args.max_calls:
        raise SystemExit(f"planned calls ({planned_calls}) exceeds --max-calls ({args.max_calls})")

    print(f"Planned Codex CLI calls: {planned_calls}")
    print(f"Max calls: {args.max_calls}")
    result = run_probe(args.case, args.prompt_mode, args.model, args.timeout)
    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
