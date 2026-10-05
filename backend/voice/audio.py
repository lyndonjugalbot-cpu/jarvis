"""Microphone in and speaker out through PortAudio (sounddevice).

The microphone delivers 80 ms blocks of 16 kHz mono int16, the frame size openWakeWord expects.
The speaker plays float audio and can be cut off mid-sentence for barge-in.
"""

import asyncio
import logging
import threading
from collections.abc import AsyncIterator

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHUNK = 1280  # 80 ms
MAX_QUEUED = 50  # 4 s; older audio is dropped if processing falls behind


def _device(name: str) -> str | None:
    return name or None


class Microphone:
    def __init__(self, device: str = "") -> None:
        self._device = _device(device)
        self._queue: asyncio.Queue[np.ndarray] | None = None
        self._stream = None

    def start(self) -> None:
        import sounddevice as sd

        loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        queue = self._queue

        def push(chunk: np.ndarray) -> None:
            if queue.qsize() >= MAX_QUEUED:
                queue.get_nowait()
            queue.put_nowait(chunk)

        def callback(indata, frames, time_info, status) -> None:
            if status:
                log.debug("microphone status: %s", status)
            loop.call_soon_threadsafe(push, indata[:, 0].copy())

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=CHUNK,
            device=self._device,
            callback=callback,
        )
        self._stream.start()

    async def chunks(self) -> AsyncIterator[np.ndarray]:
        assert self._queue is not None, "start() first"
        while True:
            yield await self._queue.get()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class Speaker:
    def __init__(self, device: str = "") -> None:
        self._device = _device(device)
        self._stop = threading.Event()

    async def play(self, audio: np.ndarray, sample_rate: int) -> bool:
        """Play to the end (True) or until stop() (False)."""
        import sounddevice as sd

        self._stop.clear()
        loop = asyncio.get_running_loop()
        finished = asyncio.Event()
        data = audio.astype(np.float32).reshape(-1, 1)
        position = 0

        def callback(outdata, frames, time_info, status) -> None:
            nonlocal position
            if self._stop.is_set():
                outdata[:] = 0
                raise sd.CallbackStop
            chunk = data[position : position + frames]
            outdata[: len(chunk)] = chunk
            outdata[len(chunk) :] = 0
            position += frames
            if position >= len(data):
                raise sd.CallbackStop

        def on_finished() -> None:  # PortAudio calls this from C and wants None back
            loop.call_soon_threadsafe(finished.set)

        stream = sd.OutputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            device=self._device,
            callback=callback,
            finished_callback=on_finished,
        )
        with stream:
            await finished.wait()
        return not self._stop.is_set()

    def stop(self) -> None:
        self._stop.set()
