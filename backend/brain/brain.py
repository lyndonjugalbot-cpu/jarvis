"""One conversation turn: recall memory, keep recent history, ask the router, remember the exchange.

Older turns of a long session are summarized in the background (never on the paid tier) once
they fall out of the history window, so they stay recallable without filling every request.
"""

import asyncio
import logging
import time
import uuid

from brain.providers.base import Reply, Turn
from brain.router import Router
from tools.registry import ToolRegistry

log = logging.getLogger(__name__)

SUMMARY_CHUNK = 20  # messages (10 exchanges) per summary
SUMMARY_PROMPT = (
    "Write a summary of this conversation for your own long-term memory, in two to four short "
    "sentences: what the user asked or told you, decisions, facts learned, anything to follow up. "
    "Plain text, no preamble. Do not call any tools.\n\n{transcript}"
)


class Brain:
    def __init__(
        self,
        router: Router,
        registry: ToolRegistry,
        *,
        history_turns: int = 20,
        memory=None,
        recall_k: int = 5,
        min_similarity: float = 0.65,
        resume_hours: float = 6,
    ) -> None:
        self._router = router
        self._registry = registry
        self._history_turns = history_turns
        self._memory = memory
        self._recall_k = recall_k
        self._min_similarity = min_similarity
        self.session = uuid.uuid4().hex[:12]
        self._history: list[tuple[str, str]] = (
            memory.recent_turns(2 * history_turns, resume_hours * 3600) if memory else []
        )
        self._summarizing: asyncio.Task | None = None

    async def _recall(self, text: str) -> tuple[str, ...]:
        if self._memory is None:
            return ()
        try:
            lines = await self._memory.context_for(
                text, session=self.session, k=self._recall_k, min_score=self._min_similarity
            )
        except Exception:
            log.exception("memory recall failed; answering without it")
            return ()
        return tuple(lines)

    async def ask(self, text: str) -> Reply:
        turn = Turn(
            id=uuid.uuid4().hex[:12],
            text=text,
            history=tuple(self._history[-2 * self._history_turns :]),
            memory=await self._recall(text),
        )
        self._registry.begin_turn(turn.id)
        started = time.monotonic()
        reply = await self._router.send(turn)
        reply.duration_s = time.monotonic() - started
        jarvis_tools = [c.name for c in self._registry.turn_calls]
        reply.tools_used = jarvis_tools + [t for t in reply.tools_used if t not in jarvis_tools]
        self._history += [("user", text), ("jarvis", reply.text)]
        log.info(
            "turn %s provider=%s tools=%s memories=%d %.1fs cost=$%.4f",
            turn.id,
            reply.provider,
            reply.tools_used,
            len(turn.memory),
            reply.duration_s,
            reply.cost_usd,
        )
        if self._memory is not None:
            try:
                await self._memory.add_exchange(self.session, text, reply.text)
            except Exception:
                log.exception("couldn't store the exchange in memory")
            self._maybe_summarize()
        return reply

    def _maybe_summarize(self) -> None:
        if self._summarizing and not self._summarizing.done():
            return
        pending = self._memory.unsummarized(self.session)
        # Only turns that have left the history window, a chunk at a time.
        if len(pending) - 2 * self._history_turns >= SUMMARY_CHUNK:
            self._summarizing = asyncio.create_task(self._summarize(pending[:SUMMARY_CHUNK]))

    async def _summarize(self, messages) -> None:
        transcript = "\n".join(f"{m.role}: {m.text}" for m in messages)
        turn = Turn(
            id=f"summary-{uuid.uuid4().hex[:8]}", text=SUMMARY_PROMPT.format(transcript=transcript)
        )
        try:
            reply = await self._router.send(turn, allow_paid=False)
            await self._memory.add_summary(
                self.session, reply.text.strip(), [m.id for m in messages]
            )
            log.info("summarized %d messages of session %s", len(messages), self.session)
        except Exception as e:
            log.info("summary skipped for now: %s", e)
