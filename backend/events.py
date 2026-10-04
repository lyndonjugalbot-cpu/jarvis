"""A small async event bus so voice, brain and HUD stay decoupled."""

import inspect
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

Handler = Callable[..., Any]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        """Call `handler(**payload)` for every event on `topic` (sync or async handlers)."""
        self._handlers[topic].append(handler)

    async def publish(self, topic: str, **payload: Any) -> None:
        for handler in list(self._handlers[topic]):
            try:
                result = handler(**payload)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                log.exception("event handler for %s failed", topic)
