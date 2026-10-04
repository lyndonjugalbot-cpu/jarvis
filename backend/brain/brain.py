"""One conversation turn: give it an id, keep recent history, ask the router."""

import logging
import time
import uuid

from brain.providers.base import Reply, Turn
from brain.router import Router
from tools.registry import ToolRegistry

log = logging.getLogger(__name__)


class Brain:
    def __init__(self, router: Router, registry: ToolRegistry, *, history_turns: int = 20) -> None:
        self._router = router
        self._registry = registry
        self._history_turns = history_turns
        self._history: list[tuple[str, str]] = []

    async def ask(self, text: str) -> Reply:
        turn = Turn(
            id=uuid.uuid4().hex[:12],
            text=text,
            history=tuple(self._history[-2 * self._history_turns :]),
        )
        self._registry.begin_turn(turn.id)
        started = time.monotonic()
        reply = await self._router.send(turn)
        reply.duration_s = time.monotonic() - started
        jarvis_tools = [c.name for c in self._registry.turn_calls]
        reply.tools_used = jarvis_tools + [t for t in reply.tools_used if t not in jarvis_tools]
        self._history += [("user", text), ("jarvis", reply.text)]
        log.info(
            "turn %s provider=%s tools=%s %.1fs cost=$%.4f",
            turn.id,
            reply.provider,
            reply.tools_used,
            reply.duration_s,
            reply.cost_usd,
        )
        return reply
