"""What every model provider (Claude plan, ChatGPT plan, local model, paid API) looks like."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Turn:
    id: str
    text: str
    history: tuple[tuple[str, str], ...] = ()  # earlier (role, text) pairs, oldest first
    memory: tuple[str, ...] = ()  # facts and recalled snippets from earlier sessions
    screen: str = ""  # what the HUD is showing that the user may refer to ("this part")


@dataclass
class Reply:
    text: str
    provider: str = ""
    tools_used: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    cost_usd: float = 0.0  # real money spent; only the paid tier sets this


HISTORY_CHARS = 6000


def compose(turn: Turn, *, include_history: bool = True, max_chars: int = HISTORY_CHARS) -> str:
    """The request as the model sees it: recalled memory, then (for a model starting fresh) the
    recent conversation, then the new message."""
    parts = []
    if turn.memory:
        remembered = "\n".join(f"- {line}" for line in turn.memory)
        parts.append(
            f"What you remember from before (background; use it only if relevant):\n{remembered}"
        )
    if include_history and turn.history:
        context = "\n".join(f"{role}: {text}" for role, text in turn.history)[-max_chars:]
        parts.append(
            f"Earlier in this conversation (context only; it already happened):\n{context}"
        )
    if turn.screen:
        parts.append(f"On the HUD right now: {turn.screen}")
    if not parts:
        return turn.text
    return "\n\n".join([*parts, f"New message:\n{turn.text}"])


def with_history(turn: Turn, max_chars: int = HISTORY_CHARS) -> str:
    return compose(turn, max_chars=max_chars)


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
