"""Decides when a spoken request has ended, from loudness alone.

The noise floor follows the quietest recent audio. Speech is anything clearly above it; the
request ends after a stretch of silence, or at a maximum length. With no speech at all for a
while, listening gives up.
"""

import numpy as np

SAMPLE_RATE = 16000


def level_db(chunk: np.ndarray) -> float:
    samples = chunk.astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0
    return 20 * np.log10(rms + 1e-9)


class Endpointer:
    WAITING, SPEAKING, DONE, TIMEOUT = "waiting", "speaking", "done", "timeout"

    def __init__(
        self,
        *,
        noise_floor_db: float = -60.0,
        speech_above_db: float = 12.0,
        silence_ms: int = 800,
        max_ms: int = 15000,
        no_speech_ms: int = 5000,
        chunk_ms: int = 80,
    ) -> None:
        self.floor = noise_floor_db
        self._above = speech_above_db
        self._silence_chunks = silence_ms // chunk_ms
        self._max_chunks = max_ms // chunk_ms
        self._no_speech_chunks = no_speech_ms // chunk_ms
        self._chunks = 0
        self._quiet = 0
        self.heard_speech = False

    def feed(self, chunk: np.ndarray) -> str:
        self._chunks += 1
        db = level_db(chunk)
        speech = db > self.floor + self._above
        if not speech:
            # The floor drifts toward the current quiet level (fast down, slow up).
            self.floor = db if db < self.floor else self.floor + 0.05 * (db - self.floor)
        if speech:
            self.heard_speech = True
            self._quiet = 0
        else:
            self._quiet += 1
        if self.heard_speech and (
            self._quiet >= self._silence_chunks or self._chunks >= self._max_chunks
        ):
            return self.DONE
        if not self.heard_speech and self._chunks >= self._no_speech_chunks:
            return self.TIMEOUT
        return self.SPEAKING if self.heard_speech else self.WAITING
