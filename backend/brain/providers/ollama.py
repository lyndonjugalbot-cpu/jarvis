"""Free local model through Ollama, with JARVIS's own tool loop: private, offline, $0.

Needs Ollama running (`ollama serve`, or the app) and a model that can call tools, pulled once:
`ollama pull qwen3:8b`. If either is missing the router simply skips this provider.
"""

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from brain.providers.base import ProviderError, Reply, Turn, with_history
from config import LocalSettings
from tools.registry import ToolRegistry

log = logging.getLogger(__name__)

MAX_ROUNDS = 6
AVAILABLE_CACHE_S = 30


class OllamaProvider:
    name = "local"
    label = "Local model"

    def __init__(
        self,
        settings: LocalSettings,
        *,
        registry: ToolRegistry,
        system_prompt: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._s = settings
        self._registry = registry
        self._system_prompt = system_prompt
        self._http = http or httpx.AsyncClient(timeout=settings.turn_timeout_s)
        self._checked_at = 0.0
        self._available = False

    async def available(self) -> bool:
        if not self._s.enabled:
            return False
        if time.monotonic() - self._checked_at < AVAILABLE_CACHE_S:
            return self._available
        self._checked_at = time.monotonic()
        try:
            response = await self._http.get(f"{self._s.host}/api/tags", timeout=3)
            names = {m.get("name", "") for m in response.json().get("models", [])}
        except (httpx.HTTPError, ValueError):
            self._available = False
            return False
        wanted = self._s.model if ":" in self._s.model else f"{self._s.model}:latest"
        self._available = wanted in names
        if not self._available:
            log.info(
                "Ollama is running but %s isn't pulled (have: %s)", self._s.model, sorted(names)
            )
        return self._available

    def _tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": s.name,
                    "description": s.description,
                    "parameters": s.input_schema,
                },
            }
            for s in self._registry.specs()
        ]

    async def send(self, turn: Turn) -> Reply:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": with_history(turn)},
        ]
        tools = self._tools()
        used: list[str] = []
        for _ in range(MAX_ROUNDS):
            try:
                response = await self._http.post(
                    f"{self._s.host}/api/chat",
                    json={
                        "model": self._s.model,
                        "messages": messages,
                        "tools": tools,
                        "stream": False,
                        "think": False,  # quicker answers from thinking models
                        "keep_alive": "10m",
                    },
                )
                response.raise_for_status()
                message = response.json()["message"]
            except (httpx.HTTPError, ValueError, KeyError) as e:
                self._checked_at = 0.0
                raise ProviderError(f"Ollama failed: {e}") from e

            calls = message.get("tool_calls") or []
            if not calls:
                return Reply(text=(message.get("content") or "").strip(), tools_used=used)
            messages.append(message)

            async def run(call: dict) -> dict:
                fn = call.get("function", {})
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                result = await self._registry.run(fn.get("name", ""), args)
                used.append(fn.get("name", ""))
                return {"role": "tool", "tool_name": fn.get("name", ""), "content": result.text}

            messages += await asyncio.gather(*(run(c) for c in calls))
        raise ProviderError("The local model kept calling tools without answering.")

    async def close(self) -> None:
        await self._http.aclose()
