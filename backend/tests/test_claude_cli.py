import json
import os
import stat
import sys
from pathlib import Path

import pytest

from brain.providers.base import ProviderError, ProviderLimitError, ProviderUnavailable, Turn
from brain.providers.claude_cli import ClaudeCliProvider, subscription_env
from config import ClaudePlanSettings

FAKE = Path(__file__).with_name("fake_claude.py")


@pytest.fixture
def fake_cli(tmp_path: Path) -> Path:
    script = tmp_path / "claude"
    script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def make_provider(fake_cli: Path, tmp_path: Path, scenario: str = "ok", **overrides):
    env = {
        "PATH": os.environ["PATH"],
        "FAKE_CLAUDE_SCENARIO": scenario,
        "FAKE_CLAUDE_LOG": str(tmp_path / "calls.jsonl"),
        "ANTHROPIC_API_KEY": "sk-should-never-reach-the-cli",
        "CLAUDECODE": "1",
    }
    settings = ClaudePlanSettings(command=str(fake_cli), **overrides)
    return ClaudeCliProvider(
        settings,
        system_prompt="test",
        mcp_config=tmp_path / "mcp.json",
        workdir=tmp_path / "work",
        env=env,
    )


def calls(tmp_path: Path) -> list[dict]:
    return [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]


async def test_reply_tools_and_warm_process(fake_cli, tmp_path):
    provider = make_provider(fake_cli, tmp_path)
    try:
        first = await provider.send(
            Turn("t1", "hello", history=(("user", "hi"), ("jarvis", "hey")))
        )
        second = await provider.send(Turn("t2", "again", history=(("user", "hello"),)))
    finally:
        await provider.close()
    assert first.text.startswith("reply 1: Earlier in this conversation")
    assert "user: hi" in first.text and first.text.endswith("hello")
    assert second.text == "reply 2: again"  # same process, so no history preamble
    assert first.tools_used == ["get_time"]
    assert len(calls(tmp_path)) == 1  # one process served both turns
    assert provider.last_rate_limit["unifiedWindows"]["five_hour"]["utilization"] == 0.25


async def test_cli_never_sees_api_keys_or_parent_session(fake_cli, tmp_path):
    provider = make_provider(fake_cli, tmp_path)
    try:
        await provider.send(Turn("t1", "hi"))
    finally:
        await provider.close()
    call = calls(tmp_path)[0]
    assert call["has_api_key"] is False
    assert call["nested_marker"] is False
    argv = call["argv"]
    assert argv[argv.index("--tools") + 1] == "WebSearch,WebFetch"
    assert argv[argv.index("--allowedTools") + 1] == "mcp__jarvis,WebSearch,WebFetch"
    assert "--strict-mcp-config" in argv and "--no-session-persistence" in argv


def test_subscription_env_keeps_oauth_token_only():
    env = subscription_env(
        {
            "ANTHROPIC_API_KEY": "x",
            "ANTHROPIC_BASE_URL": "y",
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "CLAUDE_CODE_OAUTH_TOKEN": "keep",
            "HOME": "/home/me",
        }
    )
    assert env == {"CLAUDE_CODE_OAUTH_TOKEN": "keep", "HOME": "/home/me"}


async def test_usage_limit_carries_reset_time(fake_cli, tmp_path):
    provider = make_provider(fake_cli, tmp_path, "limit")
    with pytest.raises(ProviderLimitError) as err:
        await provider.send(Turn("t1", "hi"))
    assert err.value.reset_at == 1791160200


@pytest.mark.parametrize("scenario", ["logged_out", "api_key_auth"])
async def test_not_available_without_a_plan_login(fake_cli, tmp_path, scenario):
    assert await make_provider(fake_cli, tmp_path, scenario).available() is False


async def test_refuses_a_process_that_reports_an_api_key(fake_cli, tmp_path):
    with pytest.raises(ProviderUnavailable):
        await make_provider(fake_cli, tmp_path, "api_key_source").send(Turn("t1", "hi"))


async def test_jarvis_tools_must_be_connected(fake_cli, tmp_path):
    with pytest.raises(ProviderError, match="not connected"):
        await make_provider(fake_cli, tmp_path, "mcp_failed").send(Turn("t1", "hi"))


async def test_stall_is_an_error(fake_cli, tmp_path):
    provider = make_provider(fake_cli, tmp_path, "hang", stall_timeout_s=0.5)
    with pytest.raises(ProviderError, match="no output"):
        await provider.send(Turn("t1", "hi"))


async def test_crash_is_an_error_with_stderr(fake_cli, tmp_path):
    with pytest.raises(ProviderError, match="boom"):
        await make_provider(fake_cli, tmp_path, "crash").send(Turn("t1", "hi"))
