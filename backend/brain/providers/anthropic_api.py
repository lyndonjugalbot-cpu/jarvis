"""Paid provider: the Claude API with JARVIS's tools, the last resort in the chain (spec 3.3).

Before every API call the worst case (the request's estimated input plus the full max_tokens
of output) must fit in what's left of the monthly cap, so spend can't run past it. Actual cost
comes from each response's token usage and is recorded in the budget. In "ask" mode the user
approves the paid tier once a day.
"""

import asyncio
import json
import logging
import time
from datetime import date
from typing import Any

import anthropic

from brain.budget import Budget
from brain.providers.base import (
    ProviderError,
    ProviderLimitError,
    ProviderUnavailable,
    Reply,
    Turn,
    with_history,
)
from config import PaidApiSettings
from tools.registry import Confirmer, ToolRegistry

log = logging.getLogger(__name__)

MAX_ROUNDS = 8
CHARS_PER_TOKEN = 3  # conservative, so estimates run high
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_PRICE_FACTOR = 1.25  # a refusal fallback model can cost more; bill estimates assume so
ASK_TIMEOUT_S = 30


class AnthropicApiProvider:
    name = "paid_api"
    label = "Claude API"
    paid = True

    def __init__(
        self,
        settings: PaidApiSettings,
        *,
        api_key: str,
        registry: ToolRegistry,
        budget: Budget,
        system_prompt: str,
        confirmer: Confirmer | None = None,
        client: Any = None,
    ) -> None:
        self._s = settings
        self._api_key = api_key
        self._registry = registry
        self._budget = budget
        self._system_prompt = system_prompt
        self._confirmer = confirmer
        self._client = client
        self._approved_on: date | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(
                api_key=self._api_key, max_retries=1, timeout=90
            )
        return self._client

    async def available(self) -> bool:
        return (
            self._s.enabled
            and bool(self._api_key)
            and self._budget.enabled
            and self._budget.allows(self._worst_case([], 0))
        )

    def _price(self, input_tokens: int, output_tokens: int, factor: float = 1.0) -> float:
        s = self._s
        return (
            factor
            * (input_tokens * s.input_usd_per_mtok + output_tokens * s.output_usd_per_mtok)
            / 1e6
        )

    def _worst_case(self, messages: list, tools_chars: int) -> float:
        chars = len(self._system_prompt) + tools_chars + len(json.dumps(messages, default=str))
        return self._price(chars // CHARS_PER_TOKEN, self._s.max_tokens, FALLBACK_PRICE_FACTOR)

    async def _approved(self) -> bool:
        if self._budget.fallback != "ask" or self._approved_on == date.today():
            return True
        if self._confirmer is None:
            return False
        question = (
            "Your Claude and ChatGPT plans aren't available. Use the paid Claude API? "
            f"(${self._budget.spent():.2f} of ${self._budget.cap_usd:.2f} used this month)"
        )
        try:
            ok = await asyncio.wait_for(self._confirmer(question), ASK_TIMEOUT_S)
        except TimeoutError:
            ok = False
        if ok:
            self._approved_on = date.today()
        return ok

    async def send(self, turn: Turn) -> Reply:
        if not await self._approved():
            raise ProviderUnavailable("the paid API wasn't approved")
        tools = [
            {"name": s.name, "description": s.description, "input_schema": s.input_schema}
            for s in self._registry.specs()
        ]
        tools_chars = len(json.dumps(tools))
        messages: list[dict[str, Any]] = [{"role": "user", "content": with_history(turn)}]
        used: list[str] = []
        spent = 0.0
        for _ in range(MAX_ROUNDS):
            if not self._budget.allows(self._worst_case(messages, tools_chars)):
                raise ProviderLimitError(
                    "the paid API's monthly budget is used up",
                    reset_at=self._budget.next_month_start(),
                )
            response = await self._call(messages, tools)
            cost = self._cost(response)
            spent += cost
            await self._budget.record(
                cost, response.usage.input_tokens, response.usage.output_tokens
            )

            if response.stop_reason == "refusal":
                return Reply(text="I can't help with that one.", tools_used=used, cost_usd=spent)
            if response.stop_reason in ("tool_use", "pause_turn"):
                messages.append({"role": "assistant", "content": response.content})
                calls = [b for b in response.content if b.type == "tool_use"]
                if calls:
                    results = await asyncio.gather(
                        *(self._registry.run(b.name, b.input) for b in calls)
                    )
                    used += [b.name for b in calls]
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": b.id,
                                    "content": r.text,
                                    "is_error": r.is_error,
                                }
                                for b, r in zip(calls, results, strict=True)
                            ],
                        }
                    )
                continue
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            return Reply(text=text, tools_used=used, cost_usd=spent)
        raise ProviderError("The paid API kept calling tools without answering.")

    async def _call(self, messages: list, tools: list) -> Any:
        try:
            return await self._get_client().beta.messages.create(
                model=self._s.model,
                max_tokens=self._s.max_tokens,
                system=self._system_prompt,
                tools=tools,
                messages=messages,
                output_config={"effort": self._s.effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as e:
            raise ProviderUnavailable("the Anthropic API key was rejected") from e
        except anthropic.RateLimitError as e:
            wait = int(e.response.headers.get("retry-after", "60"))
            raise ProviderLimitError("the API is rate-limiting", reset_at=time.time() + wait) from e
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            raise ProviderError(f"Claude API error: {e}") from e

    def _cost(self, response: Any) -> float:
        usage = response.usage
        fell_back = any(getattr(b, "type", "") == "fallback" for b in response.content)
        input_tokens = (
            usage.input_tokens
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
            + (getattr(usage, "cache_read_input_tokens", 0) or 0)
        )
        return self._price(
            input_tokens, usage.output_tokens, FALLBACK_PRICE_FACTOR if fell_back else 1.0
        )

    async def close(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            await self._client.close()
