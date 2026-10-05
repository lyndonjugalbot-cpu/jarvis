"""Memory tools: remember facts, search what JARVIS remembers, and forget a topic."""

from typing import Annotated, Any

from pydantic import Field

from tools.registry import ToolError, ToolSpec, tool


def _forget_summary(memory: Any, topic: str) -> str:
    found = memory.forget_preview(topic)
    parts = [
        f"{n} {word}{'' if n == 1 else 's'}"
        for n, word in (
            (found["facts"], "fact"),
            (found["exchanges"], "conversation exchange"),
            (found["summaries"], "summary"),
        )
        if n
    ]
    what = ", ".join(parts) if parts else "nothing stored yet"
    return f'Forget everything about "{topic}"? ({what})'


def make_memory_tools(memory: Any) -> list[ToolSpec]:
    @tool()
    async def remember(
        key: Annotated[
            str, Field(description='A short name, e.g. "preferred_name", "sister", "coffee_order"')
        ],
        value: Annotated[str, Field(description="What to remember")],
    ) -> dict:
        """Remember a personal fact or preference for future conversations; the same key
        replaces the old value. Use it when the user shares something worth keeping."""
        key = await memory.remember(key, value)
        return {"remembered": key, "value": value}

    @tool()
    async def recall(
        query: Annotated[str, Field(description="What to look for")],
    ) -> list[dict]:
        """Search what you remember: facts, earlier conversations, summaries and notes."""
        hits = await memory.search(query, k=8)
        return [
            {"kind": h.kind, "memory": h.describe(), "relevance": round(h.score, 2)} for h in hits
        ]

    @tool(confirm=True, summary=lambda a: _forget_summary(memory, a["topic"]))
    async def forget(
        topic: Annotated[str, Field(description="A fact's key, or any word or phrase")],
    ) -> dict:
        """Forget facts and conversation history about a topic. Notes are kept."""
        if not topic.strip():
            raise ToolError("Tell me what to forget.")
        return {"forgot": memory.forget(topic)}

    return [remember, recall, forget]
