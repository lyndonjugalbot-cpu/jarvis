"""Phase 7: voice - endpointing, speech text cleanup, yes/no, and the hands-free loop."""

import asyncio
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from voice.endpoint import Endpointer, level_db
from voice.engines import sentences, speakable
from voice.loop import VoiceLoop, yes_or_no

CHUNK = 1280
rng = np.random.default_rng(7)


def quiet(n=1):
    return [(rng.normal(0, 30, CHUNK)).astype(np.int16) for _ in range(n)]


def loud(n=1):
    t = np.arange(CHUNK) / 16000
    return [
        (np.sin(2 * np.pi * 220 * t) * 8000 + rng.normal(0, 30, CHUNK)).astype(np.int16)
        for _ in range(n)
    ]


# ---------------------------------------------------------------- endpointing


def run(endpointer, chunks):
    return [endpointer.feed(c) for c in chunks][-1]


def test_speech_then_silence_ends_the_request():
    e = Endpointer(noise_floor_db=-60)
    assert run(e, quiet(3)) == Endpointer.WAITING
    assert run(e, loud(10)) == Endpointer.SPEAKING
    assert run(e, quiet(9)) == Endpointer.SPEAKING  # 720 ms of quiet: a pause, not the end
    assert run(e, quiet(1)) == Endpointer.DONE


def test_no_speech_times_out_and_long_speech_is_cut():
    assert run(Endpointer(no_speech_ms=1000), quiet(13)) == Endpointer.TIMEOUT
    assert run(Endpointer(max_ms=2000), loud(25)) == Endpointer.DONE


def test_steady_room_noise_at_the_floor_is_not_speech():
    noisy = [(rng.normal(0, 600, CHUNK)).astype(np.int16) for _ in range(30)]
    e = Endpointer(noise_floor_db=level_db(noisy[0]))
    assert run(e, noisy) == Endpointer.WAITING


async def test_the_loop_learns_the_room_noise_while_idle():
    loop, _ = make_loop(FakeWake(set()), FakeTranscriber(), FakeVoice())
    fan = [(rng.normal(0, 600, CHUNK)).astype(np.int16) for _ in range(80)]  # ~6 s of a fan
    await feed_all(loop, fan)
    assert loop._floor_db > level_db(fan[0]) - 6  # close to the fan's level, so it isn't speech


# ---------------------------------------------------------------- text for speech, yes/no


def test_replies_are_cleaned_up_for_speaking():
    text = "**Done.** See [the docs](https://x.io) or https://y.io\n- first\n- second"
    assert speakable(text) == "Done. See the docs or first second"
    assert sentences("OK. It's 3 pm in Auckland. Rain later!") == [
        "OK. It's 3 pm in Auckland.",
        "Rain later!",
    ]
    assert (
        speakable("13.5°C, wind 18 km/h, 14% rain")
        == "13.5 degrees, wind 18 kilometres an hour, 14 percent rain"
    )


@pytest.mark.parametrize(
    ("said", "decision"),
    [("Yes please.", True), ("yeah go ahead", True), ("No.", False), ("cancel that", False),
     ("don't do it", False), ("um maybe", None), ("yes, no, I don't know", None)],
)  # fmt: skip
def test_spoken_yes_or_no(said, decision):
    assert yes_or_no(said) is decision


# ---------------------------------------------------------------- the loop


class FakeWake:
    def __init__(self, at: set[int]) -> None:
        self.at = at
        self.n = -1

    def heard(self, chunk) -> bool:
        self.n += 1
        return self.n in self.at


class FakeTranscriber:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls = 0

    async def transcribe(self, audio) -> str:
        self.calls += 1
        return self.texts.pop(0)


class FakeVoice:
    """Speaks for a number of event-loop steps, unless stopped."""

    def __init__(self, steps: int = 3) -> None:
        self.spoken: list[str] = []
        self.steps = steps
        self.stopped = False

    async def speak(self, text: str) -> bool:
        self.spoken.append(text)
        self.stopped = False
        for _ in range(self.steps):
            await asyncio.sleep(0.01)
            if self.stopped:
                return False
        return True

    def stop(self) -> None:
        self.stopped = True


def make_loop(wake, transcriber, voice, answer=None):
    states = []

    async def on_state(s):
        states.append(s)

    async def default_answer(text):
        return f"You said: {text}"

    loop = VoiceLoop(
        wake=wake, transcriber=transcriber, voice_out=voice,
        answer=answer or default_answer, on_state=on_state,
    )  # fmt: skip
    return loop, states


async def feed_all(loop, chunks, pause=0.0):
    for chunk in chunks:
        await loop.feed(chunk)
        await asyncio.sleep(pause)


async def settle(loop):
    for _ in range(50):
        await asyncio.sleep(0.01)
        if not loop._tasks:
            return


async def test_wake_word_request_and_spoken_reply():
    asked = []

    async def answer(text):
        asked.append(text)
        return "It's three o'clock."

    voice = FakeVoice()
    loop, states = make_loop(FakeWake({2}), FakeTranscriber("What time is it?"), voice, answer)
    await feed_all(loop, quiet(3) + loud(8) + quiet(10))
    await settle(loop)
    assert asked == ["What time is it?"]
    assert voice.spoken == ["It's three o'clock."]
    assert states == ["listening", "speaking", "idle"]
    assert loop.mode == VoiceLoop.IDLE


async def test_saying_the_wake_word_while_speaking_interrupts():
    voice = FakeVoice(steps=100)
    wake = FakeWake({2, 30})
    loop, states = make_loop(wake, FakeTranscriber("Tell me a long story"), voice)
    await feed_all(loop, quiet(3) + loud(8) + quiet(10))
    await asyncio.sleep(0.05)
    assert loop.mode == VoiceLoop.SPEAKING
    await feed_all(loop, quiet(10))  # chunk 30 is the wake word
    assert voice.stopped and loop.mode == VoiceLoop.LISTENING
    assert states[-2:] == ["speaking", "listening"]


async def test_background_noise_alone_is_ignored():
    voice = FakeVoice()
    loop, states = make_loop(FakeWake({0}), FakeTranscriber("you"), voice)
    await feed_all(loop, quiet(1) + loud(5) + quiet(10))
    await settle(loop)
    assert voice.spoken == [] and loop.mode == VoiceLoop.IDLE


async def test_confirmations_can_be_answered_by_voice():
    voice = FakeVoice(steps=1)
    transcriber = FakeTranscriber("Save a note about milk", "yes please")
    loop, states = make_loop(FakeWake({0}), transcriber, voice)
    decisions = []

    async def answer(text):
        decisions.append(await loop.confirm("a1", 'Save a note titled "Milk"?'))
        return "Saved."

    loop._answer = answer
    await feed_all(loop, quiet(1) + loud(6) + quiet(10), pause=0.005)
    for _ in range(20):  # the question is spoken, then JARVIS listens for the answer
        await asyncio.sleep(0.01)
        if loop.mode == VoiceLoop.ANSWERING:
            break
    await feed_all(loop, loud(6) + quiet(10), pause=0.005)
    await settle(loop)
    assert decisions == [True]
    assert voice.spoken == ['Save a note titled "Milk"? Say yes or no.', "Saved."]


async def test_typed_requests_are_not_confirmed_by_voice():
    loop, _ = make_loop(FakeWake(set()), FakeTranscriber(), FakeVoice())
    assert await loop.confirm("a1", "Send it?") is None


async def test_microphone_switched_off_hears_nothing():
    voice = FakeVoice()
    loop, states = make_loop(FakeWake({1}), FakeTranscriber("hi"), voice)
    loop.set_enabled(False)
    await feed_all(loop, quiet(2) + loud(6) + quiet(10))
    assert states == [] and voice.spoken == []


# ---------------------------------------------------------------- the real models, offline


MODELS = Path.home() / ".jarvis" / "models"


@pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("say") or not (MODELS / "whisper").exists(),
    reason="needs macOS `say` and the downloaded voice models",
)
async def test_real_wake_word_and_transcription(tmp_path):
    from voice.engines import Transcriber, WakeWord

    aiff, wav = tmp_path / "x.aiff", tmp_path / "x.wav"
    subprocess.run(
        ["say", "-v", "Daniel", "-o", aiff, "Hey Jarvis. [[slnc 400]] What time is it?"], check=True
    )
    subprocess.run(
        ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True
    )
    with wave.open(str(wav)) as w:
        speech = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = np.concatenate([np.zeros(16000, np.int16), speech, np.zeros(24000, np.int16)])
    audio = audio + rng.normal(0, 20, len(audio)).astype(np.int16)  # a little room noise

    wake = WakeWord()
    wake.load()
    transcriber = Transcriber("base.en", MODELS)
    heard = []

    async def answer(text):
        heard.append(text)
        return None

    async def on_state(s):
        pass

    loop = VoiceLoop(
        wake=wake, transcriber=transcriber, voice_out=FakeVoice(), answer=answer, on_state=on_state
    )
    await feed_all(loop, [audio[i : i + CHUNK] for i in range(0, len(audio) - CHUNK, CHUNK)])
    await settle(loop)
    for _ in range(300):
        if heard:
            break
        await asyncio.sleep(0.05)
    assert heard and "time" in heard[0].lower()
