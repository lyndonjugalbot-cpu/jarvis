"""Phase 6: long-term memory - facts, exchanges, recall across sessions, summaries, forgetting."""

import hashlib
import json
import re

import numpy as np
import pytest

from brain.brain import SUMMARY_CHUNK, Brain
from brain.providers.base import Reply, Turn, compose
from memory.store import MemoryStore
from tools.memory import make_memory_tools
from tools.notes import make_notes_tools
from tools.registry import ToolRegistry

DIM = 256
STOP = {"the", "a", "is", "my", "what", "i", "you", "and", "of", "to", "user", "jarvis"}


class WordEmbedder:
    """Deterministic stand-in for the real model: overlapping words mean similar vectors."""

    @staticmethod
    def _vector(text: str) -> np.ndarray:
        v = np.zeros(DIM, dtype=np.float32)
        for word in re.findall(r"[a-z]+", text.lower()):
            if word not in STOP:
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1
        n = np.linalg.norm(v)
        return v / n if n else v

    async def documents(self, texts):
        return np.vstack([self._vector(t) for t in texts])

    async def query(self, text):
        return self._vector(text)


class Clock:
    def __init__(self, t: float = 1_800_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def store(tmp_path, clock=None):
    return MemoryStore(tmp_path / "jarvis.db", WordEmbedder(), now=clock or Clock())


class EchoRouter:
    """Answers every request and keeps what it was sent."""

    def __init__(self) -> None:
        self.turns: list[Turn] = []
        self.allow_paid: list[bool] = []

    async def send(self, turn: Turn, *, allow_paid: bool = True) -> Reply:
        self.turns.append(turn)
        self.allow_paid.append(allow_paid)
        return Reply(text=f"reply to {turn.text[:30]}", provider="fake")


async def test_facts_replace_and_are_recallable(tmp_path):
    memory = store(tmp_path)
    assert await memory.remember("Coffee order", "flat white") == "coffee_order"
    await memory.remember("coffee_order", "long black")
    assert memory.facts() == [("coffee_order", "long black")]
    hits = await memory.search("which coffee order do I like")
    assert hits[0].kind == "fact" and "long black" in hits[0].text


async def test_a_new_session_recalls_an_earlier_one(tmp_path):
    """Spec Phase 6 done-when: JARVIS recalls something from a previous session."""
    clock = Clock()
    first = Brain(EchoRouter(), ToolRegistry([]), memory=store(tmp_path, clock), min_similarity=0.2)
    await first.ask("my cat is called Miso and loves tuna")

    clock.t += 3 * 24 * 3600  # days later: a new session, not a resumed one
    router = EchoRouter()
    later = Brain(router, ToolRegistry([]), memory=store(tmp_path, clock), min_similarity=0.2)
    await later.ask("what does my cat love to eat")
    sent = router.turns[0]
    assert sent.history == ()  # too old to resume the conversation itself...
    assert any("Miso" in line and "tuna" in line for line in sent.memory)  # ...but remembered
    assert "What you remember from before" in compose(sent)


async def test_a_restart_resumes_a_recent_conversation(tmp_path):
    clock = Clock()
    first = Brain(EchoRouter(), ToolRegistry([]), memory=store(tmp_path, clock))
    await first.ask("let's plan the trip")
    clock.t += 600
    router = EchoRouter()
    resumed = Brain(router, ToolRegistry([]), memory=store(tmp_path, clock))
    await resumed.ask("where were we?")
    assert router.turns[0].history[0] == ("user", "let's plan the trip")


async def test_facts_always_come_along_and_this_sessions_exchanges_dont_repeat(tmp_path):
    memory = store(tmp_path)
    await memory.remember("preferred_name", "Lyndon")
    router = EchoRouter()
    brain = Brain(router, ToolRegistry([]), memory=memory, min_similarity=0.0)
    await brain.ask("tell me about volcanoes")
    await brain.ask("volcanoes again please")
    second = router.turns[1]
    assert "preferred name: Lyndon" in second.memory
    assert not any("volcanoes" in line for line in second.memory)  # it's in the history already
    assert second.history[0] == ("user", "tell me about volcanoes")


async def test_old_turns_are_summarized_off_the_paid_tier(tmp_path):
    memory = store(tmp_path)
    router = EchoRouter()
    brain = Brain(router, ToolRegistry([]), memory=memory, history_turns=2)
    for i in range(2 + SUMMARY_CHUNK // 2):  # past the 2-turn window by a whole chunk
        await brain.ask(f"question number {i}")
    await brain._summarizing
    summary_turn = router.turns[-1]
    assert summary_turn.text.startswith("Write a summary") and router.allow_paid[-1] is False
    assert len(memory.unsummarized(brain.session)) == 2 * (2 + SUMMARY_CHUNK // 2) - SUMMARY_CHUNK
    hits = await memory.search("reply to question number", kinds=("summary",))
    assert hits and hits[0].kind == "summary"


async def test_forget_removes_facts_and_whole_exchanges(tmp_path):
    memory = store(tmp_path)
    await memory.remember("dentist", "Dr Lee on Queen Street")
    await memory.add_exchange("s1", "book my dentist for Tuesday", "Done, Tuesday at 9.")
    await memory.add_exchange("s1", "what's the weather", "Sunny.")
    assert memory.forget_preview("dentist") == {"facts": 1, "exchanges": 1, "summaries": 0}
    assert memory.forget("Dentist") == {"facts": 1, "exchanges": 1, "summaries": 0}
    assert memory.facts() == []
    assert [m.text for m in memory.unsummarized("s1")] == ["what's the weather", "Sunny."]
    assert not any("dentist" in h.text.lower() for h in await memory.search("dentist Tuesday"))


async def test_memory_tools_and_forget_needs_approval(tmp_path):
    memory = store(tmp_path)
    asked = []

    async def confirm(summary):
        asked.append(summary)
        return True

    reg = ToolRegistry(make_memory_tools(memory), confirmer=confirm)
    saved = json.loads((await reg.run("remember", {"key": "Sister", "value": "Ana"})).text)
    assert saved == {"remembered": "sister", "value": "Ana"}
    found = json.loads((await reg.run("recall", {"query": "sister"})).text)
    assert "Ana" in found[0]["memory"]
    result = json.loads((await reg.run("forget", {"topic": "sister"})).text)
    assert result["forgot"]["facts"] == 1
    assert asked == ['Forget everything about "sister"? (1 fact)']


async def test_saved_notes_are_recallable(tmp_path):
    memory = store(tmp_path)

    async def yes(summary):
        return True

    reg = ToolRegistry(
        make_notes_tools(tmp_path / "notes", on_saved=memory.index_note), confirmer=yes
    )
    await reg.run("write_note", {"title": "Garden", "text": "Plant tomatoes in November"})
    hits = await memory.search("when to plant tomatoes", kinds=("note",))
    assert hits and "November" in hits[0].text


def test_compose_puts_memory_first_and_history_only_when_asked():
    turn = Turn("t", "and now?", history=(("user", "hi"),), memory=("sister: Ana",))
    full = compose(turn)
    assert full.index("sister: Ana") < full.index("user: hi") < full.index("and now?")
    warm = compose(turn, include_history=False)
    assert "sister: Ana" in warm and "user: hi" not in warm
    assert compose(Turn("t", "plain")) == "plain"


@pytest.mark.parametrize("bad_topic", ["", "   "])
async def test_forget_needs_a_topic(tmp_path, bad_topic):
    async def yes(summary):
        return True

    reg = ToolRegistry(make_memory_tools(store(tmp_path)), confirmer=yes)
    assert (await reg.run("forget", {"topic": bad_topic})).is_error
