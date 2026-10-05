"""Hands-free conversation (spec 2.1): wake word -> record until silence -> transcribe -> answer
-> speak.

- Barge-in: saying the wake word while JARVIS is talking stops it and starts listening.
  Loudness alone can't be used, because the microphone also hears JARVIS's own voice.
- Spoken confirmations: during a voice request, a risky tool's question is read out and a
  spoken yes or no answers it. The HUD's thumbs-up can still answer first.

The loop is driven chunk by chunk (`feed`), so it runs the same on a real microphone and in tests.
"""

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable

import numpy as np

from voice.endpoint import Endpointer, level_db

log = logging.getLogger(__name__)

_YES = re.compile(
    r"\b(yes|yeah|yep|yup|sure|ok(ay)?|go ahead|do it|approved?|confirm(ed)?|please do)\b", re.I
)
_NO = re.compile(r"\b(no|nope|nah|cancel|stop|don'?t|do not|never ?mind)\b", re.I)
_NOISE = {
    "",
    "you",
    "thank you.",
    "thanks for watching!",
    ".",
    "bye.",
}  # whisper's usual guesses at silence


_NEGATED = re.compile(r"\b(don'?t|do not)\s+(do it|go ahead|send it|save it|approve)\b", re.I)


def yes_or_no(text: str) -> bool | None:
    no = bool(_NO.search(text))
    yes = bool(_YES.search(_NEGATED.sub("", text)))  # "don't do it" isn't a yes
    return True if yes and not no else False if no and not yes else None


class VoiceLoop:
    IDLE, LISTENING, BUSY, SPEAKING, ANSWERING = (
        "idle",
        "listening",
        "busy",
        "speaking",
        "answering",
    )

    def __init__(
        self,
        *,
        wake,
        transcriber,
        voice_out,
        answer: Callable[[str], Awaitable[str | None]],
        on_state: Callable[[str], Awaitable[None]],
        silence_ms: int = 800,
        max_listen_s: float = 15,
    ) -> None:
        self._wake = wake
        self._transcriber = transcriber
        self._voice_out = voice_out
        self._answer = answer
        self._on_state = on_state
        self._silence_ms = silence_ms
        self._max_ms = int(max_listen_s * 1000)
        self.mode = self.IDLE
        self.enabled = True
        self._floor_db = -60.0
        self._recording: list[np.ndarray] = []
        self._endpointer: Endpointer | None = None
        self._tasks: set[asyncio.Task] = set()
        self._turn_active = False
        self._confirm: tuple[str, asyncio.Future] | None = None

    # ------------------------------------------------------------ audio in
    async def run(self, chunks) -> None:
        async for chunk in chunks:
            await self.feed(chunk)

    async def feed(self, chunk: np.ndarray) -> None:
        woke = self._wake.heard(chunk)  # every chunk, so the model's window stays current
        if not self.enabled:
            return
        if self.mode == self.IDLE:
            db = level_db(chunk)
            self._floor_db = (
                db if db < self._floor_db else self._floor_db + 0.02 * (db - self._floor_db)
            )
            if woke:
                await self._listen()
        elif self.mode == self.SPEAKING and woke:
            self._voice_out.stop()  # barge-in
            await self._listen()
        elif self.mode in (self.LISTENING, self.ANSWERING):
            self._recording.append(chunk)
            status = self._endpointer.feed(chunk)
            if status == Endpointer.DONE:
                self._finish_recording()
            elif status == Endpointer.TIMEOUT:
                await self._give_up()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self._voice_out.stop()
            self.mode = self.IDLE

    # ------------------------------------------------------------ listening
    async def _listen(self, *, for_answer: bool = False) -> None:
        self.mode = self.ANSWERING if for_answer else self.LISTENING
        self._recording = []
        self._endpointer = Endpointer(
            noise_floor_db=self._floor_db, silence_ms=self._silence_ms, max_ms=self._max_ms
        )
        await self._on_state("listening")

    def _finish_recording(self) -> None:
        audio = np.concatenate(self._recording) if self._recording else np.zeros(0, np.int16)
        answering = self.mode == self.ANSWERING
        self.mode = self.BUSY
        self._spawn(self._hear_answer(audio) if answering else self._handle(audio))

    async def _give_up(self) -> None:
        if self.mode == self.ANSWERING:  # no spoken answer; the HUD or the timeout decides
            self.mode = self.BUSY
            await self._on_state("thinking")
        else:
            self.mode = self.IDLE
            await self._on_state("idle")

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ------------------------------------------------------------ a request
    async def _handle(self, audio: np.ndarray) -> None:
        self._turn_active = True
        started = time.monotonic()
        try:
            text = await self._transcriber.transcribe(audio)
            transcribed = time.monotonic()
            if text.strip().lower() in _NOISE:
                self.mode = self.IDLE
                await self._on_state("idle")
                return
            log.info("heard: %s", text)
            reply = await self._answer(text)
            answered = time.monotonic()
            log.info(
                "voice timing: transcribe %.2fs, answer %.2fs (after %.1fs of speech)",
                transcribed - started,
                answered - transcribed,
                len(audio) / 16000,
            )
            if reply:
                await self._say(reply)
            elif self.mode == self.BUSY:
                self.mode = self.IDLE
                await self._on_state("idle")
        except Exception:
            log.exception("voice request failed")
            self.mode = self.IDLE
            await self._on_state("idle")
        finally:
            self._turn_active = False

    async def _say(self, text: str) -> None:
        self.mode = self.SPEAKING
        await self._on_state("speaking")
        await self._voice_out.speak(text)
        if self.mode == self.SPEAKING:  # not interrupted
            self.mode = self.IDLE
            await self._on_state("idle")

    # ------------------------------------------------------------ spoken confirmations
    async def confirm(self, action_id: str, summary: str) -> bool | None:
        """Ask a yes/no question out loud during a voice request. None: no spoken answer."""
        if not (self.enabled and self._turn_active and self.mode == self.BUSY):
            return None
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._confirm = (action_id, future)
        self.mode = self.SPEAKING
        await self._on_state("speaking")
        await self._voice_out.speak(f"{summary} Say yes or no.")
        if future.done():
            return future.result()
        await self._listen(for_answer=True)
        try:
            return await future
        finally:
            self._confirm = None

    async def _hear_answer(self, audio: np.ndarray) -> None:
        text = await self._transcriber.transcribe(audio)
        decision = yes_or_no(text)
        log.info("confirmation answer %r -> %s", text, decision)
        if self._confirm and not self._confirm[1].done():
            self._confirm[1].set_result(decision)
        self.mode = self.BUSY
        await self._on_state("thinking")

    def cancel_confirm(self, action_id: str) -> None:
        """The question was settled elsewhere (HUD, timeout): stop asking."""
        if self._confirm and self._confirm[0] == action_id and not self._confirm[1].done():
            self._confirm[1].set_result(None)
            if self.mode == self.SPEAKING:
                self._voice_out.stop()
            if self.mode in (self.SPEAKING, self.ANSWERING):
                self.mode = self.BUSY
