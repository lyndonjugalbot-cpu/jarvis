"""Connects the core to HUD clients over the WebSocket.

HudBridge sends messages to every connected HUD and turns a confirm_request into a yes/no from
the first HUD that answers (thumbs up, a click or Y/N). HudAssistant runs typed requests through
the brain one at a time and reports state, transcript, provider and errors back.
"""

import asyncio
import itertools
import logging
from datetime import datetime
from typing import Any

from brain.router import NoProviderAvailable

log = logging.getLogger(__name__)


class HudBridge:
    def __init__(self) -> None:
        self._clients: set[Any] = set()
        self._pending: dict[str, asyncio.Future[bool]] = {}
        self._action_ids = itertools.count(1)
        self._message_ids = itertools.count(1)
        self._tasks: set[asyncio.Task] = set()
        self.voice = None  # a VoiceLoop, once voice has started
        self.screen = ""  # what the hologram stage shows, for requests like "what's this part?"

    @property
    def connected(self) -> bool:
        return bool(self._clients)

    def add(self, ws: Any) -> None:
        self._clients.add(ws)

    def remove(self, ws: Any) -> None:
        self._clients.discard(ws)

    def note_model(self, payload: dict) -> None:
        """Keep track of the HUD's holographic model: which one, whether it's broken apart, and
        the part the user picked. Each request then tells the brain."""
        model = str(payload.get("model") or "").strip()[:80]
        part = str(payload.get("part") or "").strip()[:80]
        try:
            explode = float(payload.get("explode") or 0)
        except (TypeError, ValueError):
            explode = 0.0
        if not model:
            self.screen = ""
            return
        state = "broken apart into its parts" if explode >= 0.5 else "assembled"
        self.screen = f"a holographic {model} model, {state}"
        if part:
            self.screen += f"; the user has selected its part: {part}"
        self.screen += "."

    def spawn(self, coro: Any) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def send(self, ws: Any, kind: str, payload: dict) -> None:
        await ws.send_json({"type": kind, "payload": payload, "id": f"c{next(self._message_ids)}"})

    async def broadcast(self, kind: str, payload: dict) -> None:
        for ws in list(self._clients):
            try:
                await self.send(ws, kind, payload)
            except Exception:
                log.info("dropping a HUD that stopped accepting messages")
                self._clients.discard(ws)

    async def confirm(self, summary: str) -> bool:
        """Ask the HUDs (and, during a voice request, out loud) to approve an action. The first
        answer wins; the registry's timeout counts silence as no."""
        if not self._clients and self.voice is None:
            return False
        action_id = f"a{next(self._action_ids)}"
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[action_id] = future
        approved = False
        try:
            await self.broadcast("confirm_request", {"actionId": action_id, "summary": summary})
            if self.voice is not None:
                self.spawn(self._ask_by_voice(action_id, summary))
            approved = await future
            return approved
        finally:
            self._pending.pop(action_id, None)
            if self.voice is not None:
                self.voice.cancel_confirm(action_id)
            # A task, so the HUDs hear about it even when the wait was cancelled by the timeout.
            self.spawn(
                self.broadcast("confirm_done", {"actionId": action_id, "approved": approved})
            )

    async def _ask_by_voice(self, action_id: str, summary: str) -> None:
        decision = await self.voice.confirm(action_id, summary)
        if decision is not None:
            self.resolve(action_id, decision)

    def resolve(self, action_id: str, approved: bool) -> bool:
        future = self._pending.get(action_id)
        if future is None or future.done():
            return False
        future.set_result(bool(approved))
        return True


class HudAssistant:
    def __init__(self, core: Any, bridge: HudBridge) -> None:
        self._core = core
        self._bridge = bridge
        self._lock = asyncio.Lock()

    def provider_status(self) -> dict:
        status = self._core.router.status()
        providers = {p.name: p for p in self._core.providers}
        active = status["active"]
        return {
            "active": active,
            "label": providers[active].label if active in providers else "",
            "paid": bool(getattr(providers.get(active), "paid", False)),
            "coolingDown": sorted(status["coolingDown"]),
            "order": [p.label for p in self._core.providers],
            "budget": self._core.budget.summary() if getattr(self._core, "budget", None) else None,
        }

    async def handle_text(self, text: str, *, end_state: str | None = "idle") -> str | None:
        """Run one request and return JARVIS's reply. Voice passes end_state=None and sets the
        orb itself (speaking, then idle)."""
        text = text.strip()
        if not text:
            return None
        bridge = self._bridge
        reply_text: str | None = None
        async with self._lock:  # one request at a time; later ones wait their turn
            await bridge.broadcast("transcript", {"role": "user", "text": text})
            await bridge.broadcast("state", {"state": "thinking"})
            try:
                reply = await self._core.brain.ask(text, screen=bridge.screen)
                reply_text = reply.text
                await bridge.broadcast(
                    "transcript",
                    {
                        "role": "jarvis",
                        "text": reply.text,
                        "provider": reply.provider,
                        "tools": reply.tools_used,
                        "seconds": round(reply.duration_s, 1),
                        "cost": round(reply.cost_usd, 4),
                    },
                )
            except NoProviderAvailable as e:
                when = (
                    f" The next one is back at {datetime.fromtimestamp(e.next_reset):%H:%M}."
                    if e.next_reset
                    else ""
                )
                message = f"I can't answer right now: {e}.{when}"
                await bridge.broadcast("error", {"message": message})
                await bridge.broadcast("transcript", {"role": "jarvis", "text": message})
                reply_text = message
            except Exception:
                log.exception("turn failed")
                await bridge.broadcast(
                    "error",
                    {"message": "Something went wrong on my side. The details are in the log."},
                )
            finally:
                if end_state:
                    await bridge.broadcast("state", {"state": end_state})
        return reply_text
