"""What every model provider (Claude plan, ChatGPT plan, local model, paid API) looks like."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Turn:
    id: str
    text: str
    history: tuple[tuple[str, str], ...] = ()  # earlier (role, text) pairs, oldest first


@dataclass
class Reply:
    text: str
    provider: str = ""
    tools_used: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    cost_usd: float = 0.0  # real money spent; only the paid tier sets this


HISTORY_CHARS = 6000


def with_history(turn: Turn, max_chars: int = HISTORY_CHARS) -> str:
    """The request with the recent conversation in front, for a model starting fresh."""
    if not turn.history:
        return turn.text
    context = "\n".join(f"{role}: {text}" for role, text in turn.history)[-max_chars:]
    return (
        "Earlier in this conversation (context only; it already happened):\n"
        f"{context}\n\nNew message:\n{turn.text}"
    )


class ProviderError(Exception):
    """The provider failed this turn; trying again may work."""


class ProviderLimitError(ProviderError):
    """The plan or rate limit is used up until `reset_at` (unix time), if known."""

    def __init__(self, message: str, reset_at: float | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


class ProviderUnavailable(ProviderError):
    """Not installed, not signed in, or set up in a way JARVIS refuses to use."""


class Provider(Protocol):
    name: str
    label: str

    async def available(self) -> bool: ...

    async def send(self, turn: Turn) -> Reply: ...

    async def close(self) -> None: ...
