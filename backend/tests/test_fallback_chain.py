"""Phase 5: the Codex, local and paid providers, the budget, and failover down the chain."""

import json
import os
import stat
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import httpx
import httpx2
import pytest

from brain.budget import Budget
from brain.providers.anthropic_api import AnthropicApiProvider
from brain.providers.base import ProviderLimitError, ProviderUnavailable, Turn
from brain.providers.codex_cli import CodexCliProvider, retry_at
from brain.providers.ollama import OllamaProvider
from brain.router import NoProviderAvailable, Router, SimulatedLimit
from config import CodexPlanSettings, LocalSettings, PaidApiSettings
from events import EventBus
from tools.registry import ToolRegistry, tool

FAKE_CODEX = Path(__file__).with_name("fake_codex.py")
TURN = Turn("t1", "what time is it?", history=(("user", "hi"), ("jarvis", "hello")))


@tool()
async def get_time() -> dict:
    """The time."""
    return {"time": "12:00"}


def tools() -> ToolRegistry:
    return ToolRegistry([get_time])


# ---------------------------------------------------------------- budget


class Clock:
    def __init__(self, when: datetime) -> None:
        self.when = when

    def __call__(self) -> datetime:
        return self.when


async def test_budget_tracks_the_month_and_warns_once(tmp_path):
    clock = Clock(datetime(2026, 10, 5))
    events, seen = EventBus(), []
    events.subscribe("budget.warning", lambda spent, cap: seen.append(("warning", round(spent, 2))))
    events.subscribe(
        "budget.exhausted", lambda spent, cap: seen.append(("exhausted", round(spent, 2)))
    )
    budget = Budget(tmp_path / "j.db", 10, events=events, now=clock)

    await budget.record(5.0, 1000, 100)
    assert budget.allows(4.9) and not budget.allows(5.1)
    await budget.record(3.5)
    await budget.record(0.2)  # still above 80%: no second warning
    await budget.record(1.5)
    assert seen == [("warning", 8.5), ("exhausted", 10.2)]

    clock.when = datetime(2026, 11, 1)  # a new month starts from zero
    assert budget.spent() == 0 and budget.allows(9.9)
    assert datetime.fromtimestamp(budget.next_month_start()) == datetime(2026, 12, 1)


def test_budget_off_allows_nothing(tmp_path):
    assert Budget(tmp_path / "j.db", 10, fallback="off").allows(0.0) is False


# ---------------------------------------------------------------- Codex (ChatGPT plan)


@pytest.fixture
def fake_codex(tmp_path) -> Path:
    script = tmp_path / "codex"
    script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_CODEX}" "$@"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def codex(fake_codex: Path, tmp_path: Path, scenario: str = "ok") -> CodexCliProvider:
    env = {
        "PATH": os.environ["PATH"],
        "FAKE_CODEX_SCENARIO": scenario,
        "FAKE_CODEX_LOG": str(tmp_path / "codex.jsonl"),
        "OPENAI_API_KEY": "sk-should-never-reach-codex",
    }
    return CodexCliProvider(
        CodexPlanSettings(command=str(fake_codex)),
        system_prompt="You are JARVIS.",
        mcp_url="http://127.0.0.1:9999/mcp",
        mcp_token="mcp-secret",
        workdir=tmp_path / "work",
        env=env,
    )


async def test_codex_answers_with_history_and_jarvis_tools(fake_codex, tmp_path):
    reply = await codex(fake_codex, tmp_path).send(TURN)
    assert reply.text == "codex says: what time is it?"
    assert reply.tools_used == ["get_time"]
    call = json.loads((tmp_path / "codex.jsonl").read_text())
    assert "user: hi" in call["prompt"] and call["prompt"].endswith("what time is it?")
    assert call["has_openai_key"] is False and call["mcp_token"] == "mcp-secret"
    argv = call["argv"]
    for flag in ("--ephemeral", "--ignore-user-config", "shell_tool", "unified_exec", "read-only"):
        assert flag in argv, flag
    assert 'mcp_servers.jarvis.url="http://127.0.0.1:9999/mcp"' in argv
    assert 'mcp_servers.jarvis.default_tools_approval_mode="approve"' in argv
    assert "mcp-secret" not in " ".join(argv)  # the token travels in the environment


async def test_codex_limit_has_a_reset_time(fake_codex, tmp_path):
    with pytest.raises(ProviderLimitError) as err:
        await codex(fake_codex, tmp_path, "limit").send(TURN)
    assert err.value.reset_at is not None


async def test_codex_signed_in_with_an_api_key_is_refused(fake_codex, tmp_path):
    assert await codex(fake_codex, tmp_path, "api_key_login").available() is False


def test_retry_times_in_codex_messages():
    now = datetime(2026, 10, 5, 14, 0)
    assert datetime.fromtimestamp(retry_at("try again in 2 hours 30 minutes", now)) == datetime(
        2026, 10, 5, 16, 30
    )
    assert datetime.fromtimestamp(retry_at("Try again at 3:15 PM.", now)) == datetime(
        2026, 10, 5, 15, 15
    )
    assert datetime.fromtimestamp(retry_at("try again at 9am", now)) == datetime(2026, 10, 6, 9, 0)
    assert retry_at("no idea", now) is None


# ---------------------------------------------------------------- local model (Ollama)


def ollama(handler) -> OllamaProvider:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OllamaProvider(
        LocalSettings(), registry=tools(), system_prompt="You are JARVIS.", http=http
    )


async def test_ollama_runs_the_tool_loop():
    chats = []

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})
        body = json.loads(request.content)
        chats.append(body)
        if len(chats) == 1:
            call = {"function": {"name": "get_time", "arguments": {}}}
            reply = {"role": "assistant", "content": "", "tool_calls": [call]}
            return httpx.Response(200, json={"message": reply})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "It's noon."}})

    provider = ollama(handler)
    assert await provider.available()
    reply = await provider.send(TURN)
    assert reply.text == "It's noon." and reply.tools_used == ["get_time"]
    assert chats[0]["tools"][0]["function"]["name"] == "get_time"
    assert chats[1]["messages"][-1] == {
        "role": "tool",
        "tool_name": "get_time",
        "content": '{"time": "12:00"}',
    }


async def test_ollama_without_the_model_or_server_is_unavailable():
    no_model = ollama(lambda r: httpx.Response(200, json={"models": [{"name": "llama3.2:1b"}]}))
    assert await no_model.available() is False

    def down(request):
        raise httpx.ConnectError("refused")

    assert await ollama(down).available() is False


# ---------------------------------------------------------------- paid API (Claude)


def message(content, stop_reason, input_tokens=1000, output_tokens=200):
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def anthropic_client(responses: list, seen: list):
    def handler(request):
        seen.append(json.loads(request.content))
        status, body = responses.pop(0)
        return httpx2.Response(status, json=body, headers={"retry-after": "30"})

    http = anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler))
    return anthropic.AsyncAnthropic(api_key="test", http_client=http, max_retries=0)


def paid(tmp_path, responses, seen, *, cap=10.0, fallback="auto", confirmer=None, spent=0.0):
    budget = Budget(tmp_path / "j.db", cap, fallback=fallback)
    provider = AnthropicApiProvider(
        PaidApiSettings(),
        api_key="test",
        registry=tools(),
        budget=budget,
        system_prompt="You are JARVIS.",
        confirmer=confirmer,
        client=anthropic_client(responses, seen),
    )
    return provider, budget


async def test_paid_api_tool_loop_records_the_cost(tmp_path):
    seen = []
    responses = [
        (
            200,
            message(
                [{"type": "tool_use", "id": "tu_1", "name": "get_time", "input": {}}], "tool_use"
            ),
        ),
        (200, message([{"type": "text", "text": "It's noon."}], "end_turn")),
    ]
    provider, budget = paid(tmp_path, responses, seen)
    reply = await provider.send(TURN)
    assert reply.text == "It's noon." and reply.tools_used == ["get_time"]
    # 2 calls x (1000 in x $4/M + 200 out x $20/M) = 2 x $0.008
    assert reply.cost_usd == pytest.approx(0.016) and budget.spent() == pytest.approx(0.016)
    assert seen[0]["model"] == "claude-opus-5-5" and seen[0]["output_config"] == {"effort": "low"}
    assert seen[0]["fallbacks"] == "default"
    result = seen[1]["messages"][-1]["content"][0]
    assert result == {
        "type": "tool_result",
        "tool_use_id": "tu_1",
        "content": '{"time": "12:00"}',
        "is_error": False,
    }


async def test_paid_api_never_starts_a_call_the_cap_cant_cover(tmp_path):
    seen = []
    provider, budget = paid(tmp_path, [], seen, cap=0.05)
    await budget.record(0.04)
    assert await provider.available() is False
    with pytest.raises(ProviderLimitError):
        await provider.send(TURN)
    assert seen == []  # nothing was sent, so nothing was spent


async def test_paid_api_ask_mode_needs_approval(tmp_path):
    asked = []

    async def no(question):
        asked.append(question)
        return False

    provider, _ = paid(tmp_path, [], [], fallback="ask", confirmer=no)
    with pytest.raises(ProviderUnavailable):
        await provider.send(TURN)
    assert "paid Claude API" in asked[0]


async def test_paid_api_errors_map_to_router_signals(tmp_path):
    rate_limited = (
        429,
        {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}},
    )
    provider, _ = paid(tmp_path, [rate_limited], [])
    with pytest.raises(ProviderLimitError):
        await provider.send(TURN)
    bad_key = (
        401,
        {
            "type": "error",
            "error": {"type": "authentication_error", "message": "invalid x-api-key"},
        },
    )
    provider, _ = paid(tmp_path, [bad_key], [])
    with pytest.raises(ProviderUnavailable):
        await provider.send(TURN)


# ---------------------------------------------------------------- the whole chain


async def test_each_limit_moves_the_same_request_down_the_chain(fake_codex, tmp_path):
    """Spec Phase 5: forcing each provider 'at limit' moves the request to the next one."""

    class Plan:
        def __init__(self, name):
            self.name = self.label = name

        async def available(self):
            return True

        async def send(self, turn):
            raise AssertionError("should be skipped")

        async def close(self):
            pass

    def ollama_answers(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "local here"}})

    seen = []
    paid_provider, budget = paid(
        tmp_path, [(200, message([{"type": "text", "text": "paid here"}], "end_turn"))], seen
    )
    claude = SimulatedLimit(Plan("claude_plan"))
    chatgpt = codex(fake_codex, tmp_path, "limit")
    local = ollama(ollama_answers)

    router = Router([claude, chatgpt, local, paid_provider])
    assert (await router.send(TURN)).provider == "local"

    router = Router([claude, chatgpt, SimulatedLimit(local), paid_provider])
    reply = await router.send(TURN)
    assert (reply.provider, reply.text) == ("paid_api", "paid here") and reply.cost_usd > 0

    await budget.record(budget.cap_usd)  # this month's cap is used up
    router = Router([claude, chatgpt, SimulatedLimit(local), paid_provider])
    with pytest.raises(NoProviderAvailable):
        await router.send(TURN)
    assert len(seen) == 1  # no paid call after the cap
