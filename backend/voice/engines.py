"""The voice models, all local: openWakeWord ("hey jarvis"), faster-whisper (speech to text) and
Piper (text to speech), with macOS `say` as a fallback voice. Models download once into
~/.jarvis/models (openWakeWord keeps its small files inside its own package folder)."""

import asyncio
import logging
import re
import sys
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

WAKE_MODEL = "hey_jarvis_v0.1"


# ---------------------------------------------------------------- wake word
class WakeWord:
    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        self._model = None

    def load(self) -> None:
        import openwakeword
        import openwakeword.utils
        from openwakeword.model import Model

        folder = Path(openwakeword.__file__).parent / "resources" / "models"
        path = folder / f"{WAKE_MODEL}.onnx"
        if not path.exists() or not (folder / "melspectrogram.onnx").exists():
            openwakeword.utils.download_models(model_names=[WAKE_MODEL])
        self._model = Model(wakeword_models=[str(path)], inference_framework="onnx")

    def heard(self, chunk: np.ndarray) -> bool:
        """Feed every chunk (the model keeps a running window); True on the wake word."""
        score = max(self._model.predict(chunk).values())
        if score >= self.threshold:
            self._model.reset()  # so the same utterance doesn't trigger twice
            return True
        return False


# ---------------------------------------------------------------- speech to text
class Transcriber:
    def __init__(self, model: str, models_dir: Path) -> None:
        self._name = model
        self._dir = models_dir / "whisper"
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    self._name, device="cpu", compute_type="int8", download_root=str(self._dir)
                )

    async def transcribe(self, audio: np.ndarray) -> str:
        def run() -> str:
            self.load()
            samples = audio.astype(np.float32) / 32768.0
            segments, _ = self._model.transcribe(
                samples, language="en", beam_size=1, vad_filter=True
            )
            return " ".join(s.text.strip() for s in segments).strip()

        return await asyncio.to_thread(run)


# ---------------------------------------------------------------- text to speech
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_MARKS = re.compile(r"[*_`#>|]+")
_BULLET = re.compile(r"^\s*(?:[-•▸]|\d+[.)])\s+", re.M)


_UNITS = [
    (re.compile(r"\s*°\s*C\b"), " degrees"),
    (re.compile(r"\s*°\s*F\b"), " degrees Fahrenheit"),
    (re.compile(r"\s*°"), " degrees"),
    (re.compile(r"\s*km/h\b"), " kilometres an hour"),
    (re.compile(r"\s*%"), " percent"),
]


def speakable(text: str) -> str:
    """Reply text as it should be said: no markdown, links or URLs; units in words."""
    for pattern, words in _UNITS:
        text = pattern.sub(words, text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _BULLET.sub("", text)
    text = _MARKS.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    merged: list[str] = []
    for part in parts:  # very short bits ("OK.") join the next sentence for smoother speech
        if merged and len(merged[-1]) < 20:
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


class PiperVoiceOut:
    """Speaks sentence by sentence: the first sentence plays while the next is synthesized."""

    def __init__(self, voice: str, models_dir: Path, speaker) -> None:
        self._voice_name = voice
        self._dir = models_dir / "piper"
        self._speaker = speaker
        self._voice = None
        self._stopped = False

    def load(self) -> None:
        from piper import PiperVoice
        from piper.download_voices import download_voice

        path = self._dir / f"{self._voice_name}.onnx"
        if not path.exists():
            self._dir.mkdir(parents=True, exist_ok=True)
            download_voice(self._voice_name, self._dir)
        self._voice = PiperVoice.load(str(path))

    def _synthesize(self, sentence: str) -> tuple[np.ndarray, int]:
        chunks = list(self._voice.synthesize(sentence))
        return np.concatenate([c.audio_float_array for c in chunks]), chunks[0].sample_rate

    async def speak(self, text: str) -> bool:
        """Say the text; False if stopped part-way."""
        self._stopped = False
        parts = sentences(speakable(text))
        if not parts:
            return True
        upcoming = asyncio.ensure_future(asyncio.to_thread(self._synthesize, parts[0]))
        for i in range(len(parts)):
            audio, rate = await upcoming
            if i + 1 < len(parts):
                upcoming = asyncio.ensure_future(asyncio.to_thread(self._synthesize, parts[i + 1]))
            if self._stopped or not await self._speaker.play(audio, rate):
                return False
        return True

    def stop(self) -> None:
        self._stopped = True
        self._speaker.stop()


class SayVoiceOut:
    """macOS's built-in voice (`say`), when Piper isn't wanted or available."""

    def __init__(self, voice: str = "Daniel") -> None:
        self._voice = voice
        self._proc: asyncio.subprocess.Process | None = None
        self._stopped = False

    def load(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("the 'say' voice needs macOS")

    async def speak(self, text: str) -> bool:
        self._stopped = False
        self._proc = await asyncio.create_subprocess_exec("say", "-v", self._voice, speakable(text))
        await self._proc.wait()
        return not self._stopped

    def stop(self) -> None:
        self._stopped = True
        if self._proc and self._proc.returncode is None:
            self._proc.kill()
