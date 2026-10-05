"""Claude plan provider: a warm `claude -p` process speaking stream-json.

The CLI runs signed in to the user's Claude subscription. JARVIS never hands it an API key:
those variables are removed from its environment, and a process that reports any API key
source is refused, so this provider can't turn into paid API billing.
"""

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from brain.providers.base import (
    ProviderError,
    ProviderLimitError,
    ProviderUnavailable,
    Reply,
    Turn,
    compose,
)
from config import ClaudePlanSettings

log = logging.getLogger(__name__)

MCP_PREFIX = "mcp__jarvis__"
AUTH_CACHE_S = 600
STREAM_LIMIT = 16 * 1024 * 1024

_LIMIT_TEXT = re.compile(r"usage limit|hit your limit|limit reached|rate.?limit|out of usage", re.I)
_AUTH_TEXT = re.compile(r"not logged in|/login|invalid api key|authenticat|oauth", re.I)
_EPOCH = re.compile(r"\|(\d{10})\b")


def subscription_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """The CLI's environment: no API credentials, no trace of a parent Claude Code session."""
    env = dict(os.environ if base is None else base)
    for key in list(env):
        if key.startswith("ANTHROPIC_") or key in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT"):
            del env[key]
        elif key.startswith("CLAUDE_CODE_") and key != "CLAUDE_CODE_OAUTH_TOKEN":
            del env[key]
    return env


class ClaudeCliProvider:
    name = "claude_plan"
    label = "Claude plan"

    def __init__(
        self,
        settings: ClaudePlanSettings,
        *,
        system_prompt: str,
        mcp_config: Path | None,
        workdir: Path,
        tools_busy: Callable[[], bool] = lambda: False,
        env: dict[str, str] | None = None,
    ) -> None:
        self._s = settings
        self._system_prompt = system_prompt
        self._mcp_config = mcp_config
        self._workdir = workdir
        self._tools_busy = tools_busy
        self._env = subscription_env(env)
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr_tail: list[str] = []
        self._turns_in_process = 0
        self._auth_ok_until = 0.0
        self._lock = asyncio.Lock()
        self.last_rate_limit: dict[str, Any] | None = None

    # ------------------------------------------------------------ availability
    async def available(self) -> bool:
        if not self._s.enabled:
            return False
        if time.monotonic() < self._auth_ok_until:
            return True
        try:
            proc = await asyncio.create_subprocess_exec(
                self._s.command,
                "auth",
                "status",
                "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=self._env,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), 15)
            status = json.loads(out or b"{}")
        except (OSError, TimeoutError, json.JSONDecodeError) as e:
            log.warning("claude auth status failed: %s", e)
            return False
        method = str(status.get("authMethod", "")).lower()
        ok = bool(status.get("loggedIn")) and "api" not in method and "key" not in method
        if not ok:
            log.warning("Claude CLI is not signed in to a Claude plan (authMethod=%r)", method)
            return False
        self._auth_ok_until = time.monotonic() + AUTH_CACHE_S
        return True

    # ------------------------------------------------------------ process
    def _args(self) -> list[str]:
        builtin = list(self._s.builtin_tools)
        args = [
            self._s.command,
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--no-session-persistence",
            "--setting-sources",
            "project",  # the empty workdir has none, so user hooks/plugins stay out
            "--disable-slash-commands",
            "--strict-mcp-config",
            "--system-prompt",
            self._system_prompt,
            "--tools",
            ",".join(builtin),
            "--allowedTools",
            ",".join(["mcp__jarvis", *builtin]),
        ]
        if self._mcp_config:
            args += ["--mcp-config", str(self._mcp_config)]
        if self._s.model:
            args += ["--model", self._s.model]
        if self._s.effort:
            args += ["--effort", self._s.effort]
        return args

    async def _start(self) -> None:
        self._workdir.mkdir(parents=True, exist_ok=True)
        self._stderr_tail = []
        self._turns_in_process = 0
        self._proc = await asyncio.create_subprocess_exec(
            *self._args(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._workdir,
            env=self._env,
            limit=STREAM_LIMIT,
        )
        asyncio.create_task(self._drain_stderr(self._proc))
        log.info("started claude CLI (pid %s)", self._proc.pid)

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stderr
        async for line in proc.stderr:
            self._stderr_tail = (self._stderr_tail + [line.decode(errors="replace").rstrip()])[-20:]

    async def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.returncode is not None:
            return
        if proc.stdin:
            proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), 3)
        except TimeoutError:
            proc.kill()
            await proc.wait()

    # ------------------------------------------------------------ turns
    def _compose(self, turn: Turn) -> str:
        # A warm process remembers the conversation; a fresh one gets it in the first message.
        # Recalled memory comes with every message, since it depends on what was asked.
        return compose(turn, include_history=not self._turns_in_process)

    async def send(self, turn: Turn) -> Reply:
        async with self._lock:
            if not await self.available():
                raise ProviderUnavailable("Claude CLI is not signed in to a Claude plan")
            if self._proc is None or self._proc.returncode is not None:
                await self._start()
            try:
                return await self._exchange(turn)
            except ProviderError:
                await self.close()
                raise
            except Exception as e:
                await self.close()
                raise ProviderError(f"Claude CLI failed: {e}") from e

    async def _exchange(self, turn: Turn) -> Reply:
        proc = self._proc
        assert proc and proc.stdin and proc.stdout
        message = {
            "type": "user",
            "session_id": "",
            "parent_tool_use_id": None,
            "message": {"role": "user", "content": self._compose(turn)},
        }
        proc.stdin.write((json.dumps(message) + "\n").encode())
        await proc.stdin.drain()
        self._turns_in_process += 1

        tools_used: list[str] = []
        started = time.monotonic()
        while True:
            line = await self._next_line(proc, started)
            if not line:
                await asyncio.sleep(0.1)  # let stderr catch up for the error text
                raise self._classify(" ".join(self._stderr_tail) or "Claude CLI exited")
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "system" and event.get("subtype") == "init":
                self._check_init(event)
            elif kind == "rate_limit_event":
                self._note_rate_limit(event.get("rate_limit_info") or {})
            elif kind == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use":
                        tools_used.append(block.get("name", "").removeprefix(MCP_PREFIX))
            elif kind == "result":
                if event.get("subtype") == "success" and not event.get("is_error"):
                    return Reply(text=str(event.get("result", "")).strip(), tools_used=tools_used)
                detail = (
                    event.get("result")
                    or "; ".join(map(str, event.get("errors", [])))
                    or str(event.get("subtype"))
                )
                raise self._classify(str(detail))

    async def _next_line(self, proc: asyncio.subprocess.Process, started: float) -> bytes:
        assert proc.stdout
        while True:
            if time.monotonic() - started > self._s.turn_timeout_s and not self._tools_busy():
                raise ProviderError(f"Claude CLI took longer than {self._s.turn_timeout_s:.0f}s")
            try:
                return await asyncio.wait_for(proc.stdout.readline(), self._s.stall_timeout_s)
            except TimeoutError:
                if self._tools_busy():
                    continue  # waiting on a JARVIS tool (e.g. a confirmation) is not a stall
                raise ProviderError(
                    f"Claude CLI gave no output for {self._s.stall_timeout_s:.0f}s"
                ) from None

    def _check_init(self, event: dict) -> None:
        source = event.get("apiKeySource")
        if source not in (None, "none"):
            raise ProviderUnavailable(
                f"Claude CLI is using an API key ({source}); refusing to bill it"
            )
        if self._mcp_config:
            servers = {s.get("name"): s.get("status") for s in event.get("mcp_servers", [])}
            if servers.get("jarvis") != "connected":
                raise ProviderError(
                    f"JARVIS tools are not connected to Claude ({servers.get('jarvis')})"
                )

    def _note_rate_limit(self, info: dict) -> None:
        self.last_rate_limit = info
        if info.get("status") == "rejected":
            log.warning("Claude plan limit reached: %s", info)

    def _classify(self, detail: str) -> ProviderError:
        info = self.last_rate_limit or {}
        if info.get("status") == "rejected" or _LIMIT_TEXT.search(detail):
            reset = info.get("resetsAt") if info.get("status") == "rejected" else None
            if reset is None and (m := _EPOCH.search(detail)):
                reset = int(m.group(1))
            return ProviderLimitError(f"Claude plan limit reached: {detail}", reset_at=reset)
        if _AUTH_TEXT.search(detail):
            self._auth_ok_until = 0.0
            return ProviderUnavailable(f"Claude CLI sign-in problem: {detail}")
        return ProviderError(f"Claude CLI error: {detail}")
