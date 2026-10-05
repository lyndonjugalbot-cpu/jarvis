"""Connecting JARVIS to the user's Google account."""

import asyncio
from typing import Any

from tools.registry import ToolSpec, tool


def make_google_account_tools(auth: Any) -> list[ToolSpec]:
    @tool()
    async def connect_google() -> dict:
        """Open Google's sign-in page in the browser so JARVIS can use Calendar and Gmail.
        Use it when the user asks to connect or reconnect Google. Waits up to 5 minutes."""
        await asyncio.to_thread(auth.login)
        return {"connected": True}

    return [connect_google]
