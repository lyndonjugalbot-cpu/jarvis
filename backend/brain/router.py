"""Tries providers in order and uses the first one that is available.

A provider that reports a usage limit cools down until its reset time (or `recheck_s` when it
gives none). Other failures get one retry, then the next provider takes the same turn; the
tool registry's per-turn memory stops finished tool calls from running again.
"""

import logging
import time
from collections.abc import Callable, Sequence

from brain.providers.base import (
    Provider,
    ProviderError,
    ProviderLimitError,
    ProviderUnavailable,
    Reply,
    Turn,
)
from events import EventBus

log = logging.getLogger(__name__)


class NoProviderAvailable(Exception):
    def __init__(self, failures: list[str], next_reset: float | None) -> None:
        super().__init__("; ".join(failures) or "no providers configured")
        self.failures = failures
        self.next_reset = next_reset


class Router:
    def __init__(
        self,
        providers: Sequence[Provider],
        events: EventBus | None = None,
        *,
        recheck_s: float = 900.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._providers = list(providers)
        self._events = events or EventBus()
        self._recheck_s = recheck_s
        self._clock = clock
        self._cooldown_until: dict[str, float] = {}
        self._limit_reset: dict[str, float] = {}  # cooldowns caused by a usage limit
        self.active: str | None = None

    def status(self) -> dict:
        now = self._clock()
        return {
            "active": self.active,
            "coolingDown": {n: t for n, t in self._cooldown_until.items() if t > now},
        }

    async def send(self, turn: Turn) -> Reply:
        failures: list[str] = []
        for provider in self._providers:
            until = self._cooldown_until.get(provider.name, 0.0)
            if until > self._clock():
                failures.append(f"{provider.label} is cooling down")
                continue
            if not await provider.available():
                failures.append(f"{provider.label} is not available")
                continue
            reply = await self._try(provider, turn, failures)
            if reply is not None:
                await self._mark_active(provider)
                reply.provider = provider.name
                return reply
        resets = [t for t in self._limit_reset.values() if t > self._clock()]
        raise NoProviderAvailable(failures, min(resets) if resets else None)

    async def _try(self, provider: Provider, turn: Turn, failures: list[str]) -> Reply | None:
        for attempt in (1, 2):
            try:
                return await provider.send(turn)
            except ProviderLimitError as e:
                until = e.reset_at or self._clock() + self._recheck_s
                self._cooldown_until[provider.name] = self._limit_reset[provider.name] = until
                failures.append(f"{provider.label} limit reached")
                await self._events.publish(
                    "provider.limit", provider=provider.name, label=provider.label, until=until
                )
                return None
            except ProviderUnavailable as e:
                self._cooldown_until[provider.name] = self._clock() + self._recheck_s
                self._limit_reset.pop(provider.name, None)
                failures.append(f"{provider.label}: {e}")
                return None
            except ProviderError as e:
                log.warning("%s failed (attempt %d): %s", provider.name, attempt, e)
                if attempt == 2:
                    failures.append(f"{provider.label}: {e}")
        return None

    async def _mark_active(self, provider: Provider) -> None:
        if self.active != provider.name:
            previous, self.active = self.active, provider.name
            await self._events.publish(
                "provider.active", provider=provider.name, label=provider.label, previous=previous
            )

    async def close(self) -> None:
        for provider in self._providers:
            await provider.close()
