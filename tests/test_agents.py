import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from agents import ConfigLoader, AgentInvoker, AgentCliError, AgentTimeoutError  # noqa: E402
from models import AgentConfig, Role  # noqa: E402


def _valid_config() -> dict:
    return {
        name: {"command": name.lower(), "args": [], "prompt_mode": "arg"}
        for name in ["Claude", "Codex", "Grok", "agy"]
    }


def _write_config(tmp_path: Path, payload) -> Path:
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_config_preserves_definition_order(tmp_path: Path) -> None:
    configs = ConfigLoader().load(_write_config(tmp_path, _valid_config()))
    assert [config.name for config in configs] == ["Claude", "Codex", "Grok", "agy"]
    assert all(config.response_mode == "json" for config in configs)
    assert all(config.normalize_with is None for config in configs)


def test_config_loads_optional_natural_text_response_mode(tmp_path: Path) -> None:
    payload = _valid_config()
    payload["Codex"].update(response_mode="natural_text", normalize_with="local")
    configs = ConfigLoader().load(_write_config(tmp_path, payload))
    codex = next(config for config in configs if config.name == "Codex")
    assert codex.response_mode == "natural_text"
    assert codex.normalize_with == "local"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.pop("agy"),
        lambda data: data["Claude"].pop("command"),
        lambda data: data["Claude"].update(command=""),
        lambda data: data["Claude"].update(args="not-an-array"),
        lambda data: data["Claude"].update(prompt_mode="invalid"),
        lambda data: data["Claude"].update(response_mode="invalid"),
        lambda data: data["Claude"].update(normalize_with=[]),
    ],
)
def test_invalid_config_is_rejected(tmp_path: Path, mutate) -> None:
    data = _valid_config()
    mutate(data)
    with pytest.raises(ValueError):
        ConfigLoader().load(_write_config(tmp_path, data))


def test_invalid_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "agents.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        ConfigLoader().load(path)


def test_duplicate_player_name_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "agents.json"
    path.write_text(
        '{"Claude":{"command":"a","args":[],"prompt_mode":"arg"},'
        '"Codex":{"command":"b","args":[],"prompt_mode":"arg"},'
        '"Grok":{"command":"c","args":[],"prompt_mode":"arg"},'
        '"agy":{"command":"d","args":[],"prompt_mode":"stdin"},'
        '"Claude":{"command":"e","args":[],"prompt_mode":"arg"}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate player name"):
        ConfigLoader().load(path)


def _write_prompt(path: Path, body: str) -> None:
    path.write_text(
        "# stub\n\n## 用途\n\nstub\n\n## 本文\n\n```text\n" + body + "\n```\n",
        encoding="utf-8",
    )


def _prepare_prompts(tmp_path: Path) -> Path:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    _write_prompt(prompts_dir / "common_player_prompt.md", "COMMON {{player_name}}")
    _write_prompt(prompts_dir / "villager_prompt.md", "VILLAGER {{player_name}}")
    _write_prompt(prompts_dir / "seer_prompt.md", "SEER {{player_name}}")
    _write_prompt(prompts_dir / "werewolf_prompt.md", "WEREWOLF {{player_name}}")
    _write_prompt(prompts_dir / "night_seer_prompt.md", "NIGHT {{player_name}} candidates={{candidates}}")
    _write_prompt(prompts_dir / "speech_prompt.md", "SPEECH {{player_name}} log={{public_log}} seer={{seer_result_summary}}")
    _write_prompt(prompts_dir / "vote_prompt.md", "VOTE {{player_name}} log={{public_log}} candidates={{candidates}} seer={{seer_result_summary}}")
    return prompts_dir


def test_agent_invoker_arg_mode(tmp_path: Path) -> None:
    prompts_dir = _prepare_prompts(tmp_path)
    config = AgentConfig(name="Claude", command="claude", args=["-p"], prompt_mode="arg")
    invoker = AgentInvoker([config], prompts_dir, timeout=12.5)

    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = '{"target": "Codex"}'
    mock_res.stderr = ""

    with patch("subprocess.run", return_value=mock_res) as mock_run:
        res = invoker.generate_night_action("Claude", ["Codex", "Grok"])
        assert res == '{"target": "Codex"}'

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert cmd[:-1] == ["claude", "-p"]
        assert "COMMON Claude" in cmd[-1]
        assert kwargs["input"] is None
        assert kwargs["shell"] is False
        assert kwargs["timeout"] == 12.5
        import tempfile
        assert Path(kwargs["cwd"]).parent == Path(tempfile.gettempdir())


def test_agent_invoker_stdin_mode(tmp_path: Path) -> None:
    prompts_dir = _prepare_prompts(tmp_path)
    config = AgentConfig(name="Codex", command="codex", args=["exec"], prompt_mode="stdin")
    invoker = AgentInvoker([config], prompts_dir, timeout=5.0)

    # schema-valid (speech + reason) so the Q63 retry path (below) does not
    # kick in here; this test only covers stdin plumbing.
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = '{"speech": "hello", "reason": "test"}'
    mock_res.stderr = ""

    with patch("subprocess.run", return_value=mock_res) as mock_run:
        res = invoker.generate_speech("Codex", Role.VILLAGER, "public log", "seer summary")
        assert res == '{"speech": "hello", "reason": "test"}'

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert cmd == ["codex", "exec"]
        assert "COMMON Codex" in kwargs["input"]
        assert "seer=seer summary" in kwargs["input"]
        assert kwargs["shell"] is False
        assert kwargs["timeout"] == 5.0


def test_agent_invoker_cli_error(tmp_path: Path) -> None:
    prompts_dir = _prepare_prompts(tmp_path)
    config = AgentConfig(name="Grok", command="grok", args=[], prompt_mode="arg")
    invoker = AgentInvoker([config], prompts_dir)

    mock_res = MagicMock()
    mock_res.returncode = 1
    mock_res.stdout = ""
    mock_res.stderr = "some stderr error description"

    with patch("subprocess.run", return_value=mock_res):
        with pytest.raises(AgentCliError) as exc_info:
            invoker.generate_vote("Grok", Role.WEREWOLF, ["Claude", "Codex"], "log")

        assert exc_info.value.returncode == 1
        assert "some stderr error description" in exc_info.value.stderr


def test_agent_invoker_timeout_error(tmp_path: Path) -> None:
    prompts_dir = _prepare_prompts(tmp_path)
    config = AgentConfig(name="agy", command="agy", args=[], prompt_mode="arg")
    invoker = AgentInvoker([config], prompts_dir, timeout=10.0)

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["agy"], timeout=10.0, output=b"partial stdout", stderr=b"partial stderr")):
        with pytest.raises(AgentTimeoutError) as exc_info:
            invoker.generate_speech("agy", Role.VILLAGER, "log")

        assert "timed out" in str(exc_info.value)
        assert exc_info.value.stdout == "partial stdout"
        assert exc_info.value.stderr == "partial stderr"


def test_agent_invoker_command_not_found(tmp_path: Path) -> None:
    prompts_dir = _prepare_prompts(tmp_path)
    config = AgentConfig(name="Grok", command="non-existent-cmd", args=[], prompt_mode="arg")
    invoker = AgentInvoker([config], prompts_dir)

    with patch("subprocess.run", side_effect=FileNotFoundError("No such file")):
        with pytest.raises(AgentCliError) as exc_info:
            invoker.generate_speech("Grok", Role.VILLAGER, "log")

        assert exc_info.value.returncode == 127
        assert "not found" in str(exc_info.value)


def _fake_run_capturing_agents_md(captured: dict, stdout: str = '{"speech": "hi", "reason": "x"}'):
    def fake_run(cmd, **kwargs):
        cwd = Path(kwargs["cwd"])
        agents_md = cwd / "AGENTS.md"
        captured["exists"] = agents_md.exists()
        captured["content"] = agents_md.read_text(encoding="utf-8") if agents_md.exists() else None
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = stdout
        mock_res.stderr = ""
        return mock_res

    return fake_run


def test_agent_invoker_writes_local_agents_md_for_codex(tmp_path: Path) -> None:
    """QandA.md Q62: Codex only, a local AGENTS.md is written into its
    per-call temp cwd before the CLI is invoked."""
    prompts_dir = _prepare_prompts(tmp_path)
    config = AgentConfig(name="Codex", command="codex.cmd", args=["exec"], prompt_mode="arg")
    invoker = AgentInvoker([config], prompts_dir)

    captured: dict = {}
    with patch("subprocess.run", side_effect=_fake_run_capturing_agents_md(captured)):
        invoker.generate_speech("Codex", Role.VILLAGER, "log")

    assert captured["exists"] is True
    assert "開発エージェントではありません" in captured["content"]
    assert "情報が不足しています" in captured["content"]


def test_agent_invoker_writes_natural_text_agents_md_for_codex_natural_mode(tmp_path: Path) -> None:
    prompts_dir = _prepare_prompts(tmp_path)
    config = AgentConfig(
        name="Codex",
        command="codex.cmd",
        args=["exec"],
        prompt_mode="stdin",
        response_mode="natural_text",
        normalize_with="local",
    )
    invoker = AgentInvoker([config], prompts_dir)

    captured: dict = {}
    with patch(
        "subprocess.run",
        side_effect=_fake_run_capturing_agents_md(captured, stdout="私は村人です。"),
    ):
        res = invoker.generate_speech("Codex", Role.VILLAGER, "log")

    assert res == "私は村人です。"
    assert captured["exists"] is True
    assert "日本語の普通文" in captured["content"]
    assert "JSONオブジェクト" not in captured["content"]


@pytest.mark.parametrize("player_name", ["Claude", "Grok", "agy"])
def test_agent_invoker_does_not_write_agents_md_for_non_codex(tmp_path: Path, player_name: str) -> None:
    prompts_dir = _prepare_prompts(tmp_path)
    config = AgentConfig(name=player_name, command=player_name.lower(), args=[], prompt_mode="arg")
    invoker = AgentInvoker([config], prompts_dir)

    captured: dict = {}
    with patch("subprocess.run", side_effect=_fake_run_capturing_agents_md(captured)):
        invoker.generate_speech(player_name, Role.VILLAGER, "log")

    assert captured["exists"] is False


def _sequenced_run(*stdouts: str):
    """subprocess.run side_effect that returns each stdout in turn."""
    responses = list(stdouts)

    def fake_run(cmd, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = responses.pop(0)
        mock_res.stderr = ""
        return mock_res

    return fake_run


def test_codex_retries_once_on_semantic_error_and_uses_second_response(tmp_path: Path) -> None:
    """QandA.md Q63: a schema-invalid-but-syntactically-valid Codex reply
    (e.g. {"status": "ok"}) triggers exactly one reprompt, and the reprompt
    quotes the required schema/keys."""
    prompts_dir = _prepare_prompts(tmp_path)
    config = AgentConfig(name="Codex", command="codex.cmd", args=["exec"], prompt_mode="arg")
    invoker = AgentInvoker([config], prompts_dir)

    with patch(
        "subprocess.run",
        side_effect=_sequenced_run('{"status": "ok"}', '{"speech": "hi", "reason": "ok"}'),
    ) as mock_run:
        res = invoker.generate_speech("Codex", Role.VILLAGER, "log")

    assert res == '{"speech": "hi", "reason": "ok"}'
    assert mock_run.call_count == 2
    first_prompt = mock_run.call_args_list[0].args[0][-1]
    second_prompt = mock_run.call_args_list[1].args[0][-1]
    assert '{"status": "ok"}' not in first_prompt
    assert '{"status": "ok"}' in second_prompt
    assert "speech, reason" in second_prompt
    assert '{"speech":"あなたの発言内容","reason":"その発言をした意図"}' in second_prompt


def test_codex_no_retry_when_first_response_is_already_valid(tmp_path: Path) -> None:
    prompts_dir = _prepare_prompts(tmp_path)
    config = AgentConfig(name="Codex", command="codex.cmd", args=["exec"], prompt_mode="arg")
    invoker = AgentInvoker([config], prompts_dir)

    with patch(
        "subprocess.run", side_effect=_sequenced_run('{"speech": "hi", "reason": "ok"}')
    ) as mock_run:
        res = invoker.generate_speech("Codex", Role.VILLAGER, "log")

    assert res == '{"speech": "hi", "reason": "ok"}'
    mock_run.assert_called_once()


def test_codex_no_retry_on_syntax_error(tmp_path: Path) -> None:
    """Only a "semantic" error (valid JSON, wrong schema) retries; prose
    ("syntax") responses are left to the existing fallback mechanism."""
    prompts_dir = _prepare_prompts(tmp_path)
    config = AgentConfig(name="Codex", command="codex.cmd", args=["exec"], prompt_mode="arg")
    invoker = AgentInvoker([config], prompts_dir)

    with patch(
        "subprocess.run", side_effect=_sequenced_run("役職を教えてください。")
    ) as mock_run:
        res = invoker.generate_speech("Codex", Role.VILLAGER, "log")

    assert res == "役職を教えてください。"
    mock_run.assert_called_once()


def test_non_codex_semantic_error_does_not_retry(tmp_path: Path) -> None:
    prompts_dir = _prepare_prompts(tmp_path)
    config = AgentConfig(name="Claude", command="claude", args=["-p"], prompt_mode="arg")
    invoker = AgentInvoker([config], prompts_dir)

    with patch(
        "subprocess.run", side_effect=_sequenced_run('{"status": "ok"}')
    ) as mock_run:
        res = invoker.generate_speech("Claude", Role.VILLAGER, "log")

    assert res == '{"status": "ok"}'
    mock_run.assert_called_once()
