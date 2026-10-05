"""Starts voice inside the core server: loads the models in the background, opens the microphone,
and connects the voice loop to the HUD (state, transcript, confirmations, the Mic indicator)."""

import asyncio
import logging
from pathlib import Path

import numpy as np

from config import VoiceSettings
from voice.audio import Microphone, Speaker
from voice.engines import PiperVoiceOut, SayVoiceOut, Transcriber, WakeWord
from voice.loop import VoiceLoop

log = logging.getLogger(__name__)

SILENCE_CHECK_CHUNKS = 40  # ~3 s


class VoiceService:
    def __init__(self, settings: VoiceSettings, models_dir: Path, assistant, bridge) -> None:
        self._s = settings
        self._models_dir = models_dir
        self._assistant = assistant
        self._bridge = bridge
        self._mic = Microphone(settings.input_device)
        self.loop: VoiceLoop | None = None
        self._task: asyncio.Task | None = None
        self.state = "off"

    async def _mic_state(self, state: str, message: str = "") -> None:
        self.state = state
        await self._bridge.broadcast("mic", {"state": state, "message": message})

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        await self._mic_state("starting", "Loading the voice models...")
        try:
            wake = WakeWord(self._s.wake_threshold)
            transcriber = Transcriber(self._s.whisper_model, self._models_dir)
            if self._s.tts == "say":
                voice_out = SayVoiceOut(self._s.say_voice)
            else:
                voice_out = PiperVoiceOut(
                    self._s.piper_voice, self._models_dir, Speaker(self._s.output_device)
                )
            await asyncio.gather(
                asyncio.to_thread(wake.load),
                asyncio.to_thread(transcriber.load),
                asyncio.to_thread(voice_out.load),
            )
            self._mic.start()
        except Exception as e:
            log.exception("voice couldn't start")
            await self._mic_state("unavailable", f"Voice couldn't start: {e}")
            return

        async def answer(text: str) -> str | None:
            return await self._assistant.handle_text(text, end_state=None)

        async def on_state(state: str) -> None:
            await self._bridge.broadcast("state", {"state": state})
            await self._mic_state("listening" if state == "listening" else "wake")

        self.loop = VoiceLoop(
            wake=wake,
            transcriber=transcriber,
            voice_out=voice_out,
            answer=answer,
            on_state=on_state,
            silence_ms=self._s.silence_ms,
            max_listen_s=self._s.max_listen_s,
        )
        self._bridge.voice = self.loop
        await self._mic_state("wake", 'Say "Hey Jarvis".')
        log.info("voice ready: listening for the wake word")
        try:
            await self.loop.run(self._checked(self._mic.chunks()))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("voice stopped")
            await self._mic_state("unavailable", f"Voice stopped: {e}")

    async def _checked(self, chunks):
        """Pass chunks through, warning once if the microphone only gives digital silence:
        that's what macOS does when the app hasn't been allowed to use the microphone."""
        seen = 0
        silent = True
        async for chunk in chunks:
            if seen < SILENCE_CHECK_CHUNKS:
                seen += 1
                silent = silent and not np.any(chunk)
                if seen == SILENCE_CHECK_CHUNKS and silent:
                    await self._mic_state(
                        "unavailable",
                        "The microphone is silent. Allow microphone access for your terminal in "
                        "System Settings > Privacy & Security > Microphone, then restart the core.",
                    )
            yield chunk

    async def set_enabled(self, enabled: bool) -> None:
        if self.loop is None:
            return
        self.loop.set_enabled(enabled)
        await self._mic_state("wake" if enabled else "off", "" if enabled else "Microphone off.")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._mic.stop()
