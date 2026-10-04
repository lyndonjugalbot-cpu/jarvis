import pytest

from brain.providers.base import ProviderError, ProviderLimitError, ProviderUnavailable, Reply, Turn
from brain.router import NoProviderAvailable, Router
from events import EventBus


class FakeProvider:
    def __init__(self, name: str, outcomes: list, available: bool = True) -> None:
        self.name = name
        self.label = name.title()
        self._outcomes = outcomes
        self._available = available
        self.sent = 0

    async def available(self) -> bool:
        return self._available

    async def send(self, turn: Turn) -> Reply:
        self.sent += 1
        outcome = self._outcomes.pop(0) if self._outcomes else "ok"
        if isinstance(outcome, Exception):
            raise outcome
        return Reply(text=f"{self.name}: {turn.text}")

    async def close(self) -> None:
        pass


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


TURN = Turn("t1", "hi")


async def test_first_available_provider_answers():
    a, b = FakeProvider("a", []), FakeProvider("b", [])
    reply = await Router([a, b]).send(TURN)
    assert (reply.text, reply.provider, b.sent) == ("a: hi", "a", 0)


async def test_limit_cools_down_until_reset_then_returns():
    clock = Clock()
    a = FakeProvider("a", [ProviderLimitError("limit", reset_at=1500.0)])
    b = FakeProvider("b", [])
    events, seen = EventBus(), []
    events.subscribe(
        "provider.limit", lambda **e: seen.append(("limit", e["provider"], e["until"]))
    )
    events.subscribe("provider.active", lambda **e: seen.append(("active", e["provider"])))
    router = Router([a, b], events, clock=clock)

    assert (await router.send(TURN)).provider == "b"
    assert (await router.send(TURN)).provider == "b"
    assert a.sent == 1  # not retried while cooling down
    clock.now = 1501.0
    assert (await router.send(TURN)).provider == "a"
    assert seen == [("limit", "a", 1500.0), ("active", "b"), ("active", "a")]


async def test_limit_without_reset_time_rechecks_later():
    clock = Clock()
    a = FakeProvider("a", [ProviderLimitError("limit")])
    router = Router([a, FakeProvider("b", [])], clock=clock, recheck_s=900)
    await router.send(TURN)
    assert router.status()["coolingDown"] == {"a": 1900.0}


async def test_other_errors_get_one_retry():
    a = FakeProvider("a", [ProviderError("blip")])
    assert (await Router([a]).send(TURN)).provider == "a"
    assert a.sent == 2


async def test_two_errors_move_on():
    a = FakeProvider("a", [ProviderError("x"), ProviderError("y")])
    assert (await Router([a, FakeProvider("b", [])]).send(TURN)).provider == "b"


async def test_nothing_available_reports_next_reset():
    clock = Clock()
    a = FakeProvider("a", [ProviderLimitError("limit", reset_at=2000.0)])
    b = FakeProvider("b", [ProviderUnavailable("signed out")])
    c = FakeProvider("c", [], available=False)
    with pytest.raises(NoProviderAvailable) as err:
        await Router([a, b, c], clock=clock).send(TURN)
    assert err.value.next_reset == 2000.0
    assert len(err.value.failures) == 3
