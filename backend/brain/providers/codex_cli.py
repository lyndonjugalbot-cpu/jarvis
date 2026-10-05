"""ChatGPT plan provider: the official Codex CLI (`codex exec --json`), one process per turn.

Codex runs signed in with the user's ChatGPT plan. Its shell tools are disabled and its sandbox
is read-only in an empty folder, so it can only act through JARVIS's tools (MCP) and its own web
search. OpenAI API keys are removed from its environment, and a CLI signed in with an API key
is refused, so this provider can't turn into pay-per-token billing.
"""

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from brain.providers.base import (
    ProviderError,
    ProviderLimitError,
    ProviderUnavailable,
    Reply,
    Turn,
    with_history,
)
from config import CodexPlanSettings

log = logging.getLogger(__name__)

AUTH_CACHE_S = 600
STREAM_LIMIT = 16 * 1024 * 1024
TOKEN_ENV = "JARVIS_MCP_TOKEN"

_LIMIT_TEXT = re.compile(r"usage limit|hit your limit|rate.?limit|quota", re.I)
_AUTH_TEXT = re.compile(r"401|unauthori[sz]ed|not logged in|log ?in again|codex login", re.I)
_IN = re.compile(
    r"try again in ((?:\d+\s*(?:days?|hours?|minutes?|mins?|seconds?)[\s,and]*)+)", re.I
)
_AT = re.compile(r"try again at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I)
_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def retry_at(text: str, now: datetime | None = None) -> float | None:
    """When a usage-limit message says to come back, as unix time."""
    now = now or datetime.now()
    if m := _IN.search(text):
        seconds = sum(
            int(n) * _UNITS[u[0].lower()]
            for n, u in re.findall(r"(\d+)\s*(day|hour|min|second)", m.group(1), re.I)
        )
        return (now + timedelta(seconds=seconds)).timestamp() if seconds else None
    if m := _AT.search(text):
        hour, minute, half = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if half == "pm" and hour < 12:
            hour += 12
        if half == "am" and hour == 12:
            hour = 0
        when = now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
        return (when if when > now else when + timedelta(days=1)).timestamp()
    return None


def toml_string(value: str) -> str:
    return json.dumps(value)  # a JSON string is a valid TOML basic string


def plan_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID"):
        env.pop(key, None)
    return env


class CodexCliProvider:
    name = "codex_plan"
    label = "ChatGPT plan"

    def __init__(
        self,
        settings: CodexPlanSettings,
        *,
        system_prompt: str,
        mcp_url: str | None,
        mcp_token: str = "",
        workdir: Path,
        tools_busy: Callable[[], bool] = lambda: False,
        env: dict[str, str] | None = None,
    ) -> None:
        self._s = settings
        self._system_prompt = system_prompt
        self._mcp_url = mcp_url
        self._workdir = workdir
        self._tools_busy = tools_busy
        self._env = plan_env(env)
        if mcp_token:
            self._env[TOKEN_ENV] = mcp_token  # never on the command line
        self._auth_ok_until = 0.0
        self._lock = asyncio.Lock()

    async def available(self) -> bool:
        if not self._s.enabled:
            return False
        if time.monotonic() < self._auth_ok_until:
            return True
        try:
            proc = await asyncio.create_subprocess_exec(
                self._s.command, "login", "status",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                env=self._env,
            )  # fmt: skip
            out, _ = await asyncio.wait_for(proc.communicate(), 15)
        except (OSError, TimeoutError) as e:
            log.warning("codex login status failed: %s", e)
            return False
        status = out.decode(errors="replace")
        if proc.returncode != 0 or "chatgpt" not in status.lower():
            log.warning("Codex CLI is not signed in with a ChatGPT plan: %s", status.strip())
            return False
        self._auth_ok_until = time.monotonic() + AUTH_CACHE_S
        return True

    def _args(self) -> list[str]:
        args = [
            self._s.command, "exec", "--json", "--ephemeral",
            "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
            "--sandbox", "read-only",
            "--disable", "shell_tool", "--disable", "unified_exec",
            "-C", str(self._workdir),
            "-c", f"developer_instructions={toml_string(self._system_prompt)}",
            "-c", f"web_search={toml_string('live' if self._s.web_search else 'disabled')}",
        ]  # fmt: skip
        if self._mcp_url:
            args += [
                "-c", f"mcp_servers.jarvis.url={toml_string(self._mcp_url)}",
                "-c", f"mcp_servers.jarvis.bearer_token_env_var={toml_string(TOKEN_ENV)}",
                "-c", "mcp_servers.jarvis.tool_timeout_sec=60",
                "-c", "mcp_servers.jarvis.required=true",
                # JARVIS asks the user itself before risky tools, so Codex shouldn't block them.
                "-c", 'mcp_servers.jarvis.default_tools_approval_mode="approve"',
            ]  # fmt: skip
        if self._s.model:
            args += ["-m", self._s.model]
        return [*args, "-"]  # the prompt comes on stdin

    async def send(self, turn: Turn) -> Reply:
        async with self._lock:
            if not await self.available():
                raise ProviderUnavailable("Codex CLI is not signed in with a ChatGPT plan")
            self._workdir.mkdir(parents=True, exist_ok=True)
            proc = await asyncio.create_subprocess_exec(
                *self._args(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workdir,
                env=self._env,
                limit=STREAM_LIMIT,
            )
            try:
                return await self._run(proc, with_history(turn))
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()

    async def _run(self, proc: asyncio.subprocess.Process, prompt: str) -> Reply:
        assert proc.stdin and proc.stdout and proc.stderr
        proc.stdin.write(prompt.encode())
        await proc.stdin.drain()
        proc.stdin.close()

        started = time.monotonic()
        answer = ""
        failure = ""
        tools_used: list[str] = []
        completed = False
        while True:
            line = await self._next_line(proc, started)
            if not line:
                break
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            item = event.get("item") or {}
            if kind == "item.completed":
                if item.get("type") == "agent_message":
                    answer = item.get("text", "")
                elif item.get("type") == "mcp_tool_call":
                    tools_used.append(str(item.get("tool") or item.get("name") or "tool"))
                elif item.get("type") == "web_search":
                    tools_used.append("web_search")
                elif item.get("type") == "error":
                    log.info("codex notice: %s", item.get("message"))  # warnings, not failures
            elif kind == "turn.completed":
                completed = True
            elif kind == "turn.failed":
                failure = str((event.get("error") or {}).get("message", "turn failed"))
            elif kind == "error":
                failure = str(event.get("message", "error"))

        stderr = (await proc.stderr.read()).decode(errors="replace")[-2000:]
        await proc.wait()
        if completed and answer and not failure:
            return Reply(text=answer.strip(), tools_used=tools_used)
        raise self._classify(failure or stderr or f"Codex exited with code {proc.returncode}")

    async def _next_line(self, proc: asyncio.subprocess.Process, started: float) -> bytes:
        assert proc.stdout
        while True:
            if time.monotonic() - started > self._s.turn_timeout_s and not self._tools_busy():
                raise ProviderError(f"Codex took longer than {self._s.turn_timeout_s:.0f}s")
            try:
                return await asyncio.wait_for(proc.stdout.readline(), self._s.stall_timeout_s)
            except TimeoutError:
                if self._tools_busy():
                    continue
                raise ProviderError(
                    f"Codex gave no output for {self._s.stall_timeout_s:.0f}s"
                ) from None

    def _classify(self, detail: str) -> ProviderError:
        if _LIMIT_TEXT.search(detail):
            return ProviderLimitError(
                f"ChatGPT plan limit reached: {detail}", reset_at=retry_at(detail)
            )
        if _AUTH_TEXT.search(detail):
            self._auth_ok_until = 0.0
            return ProviderUnavailable(f"Codex sign-in problem: {detail}")
        return ProviderError(f"Codex error: {detail}")

    async def close(self) -> None:
        pass
