"""HUD tools: put information on screen as floating panels."""

import secrets
from typing import Annotated, Any, Literal

from pydantic import Field

from tools.registry import ToolSpec, tool


def make_hud_tools(bridge: Any) -> list[ToolSpec]:
    @tool()
    async def show_panel(
        title: Annotated[str, Field(description="Short panel title")],
        data: Annotated[
            str | list[str],
            Field(description="Text for a text panel, or short lines for a list panel"),
        ],
        type: Annotated[Literal["text", "list"], Field(description="Panel type")] = "text",
        panel_id: Annotated[
            str, Field(description="An id from an earlier show_panel, to update that panel")
        ] = "",
    ) -> dict:
        """Show information on the HUD as a floating panel: lists, notes, search results, steps,
        anything worth reading. Keep the spoken reply short and point to the panel."""
        if not bridge.connected:
            return {"shown": False, "reason": "No HUD is connected, so answer in words instead."}
        if type == "list" and isinstance(data, str):
            data = [line.strip() for line in data.splitlines() if line.strip()]
        if type == "text" and isinstance(data, list):
            data = "\n".join(data)
        pid = panel_id or f"p{secrets.token_hex(3)}"
        await bridge.broadcast(
            "show_panel", {"panel": {"id": pid, "type": type, "title": title, "data": data}}
        )
        return {"shown": True, "panel_id": pid}

    @tool()
    async def close_panel(
        panel_id: Annotated[str, Field(description="The id show_panel returned")],
    ) -> dict:
        """Close a panel that show_panel opened."""
        await bridge.broadcast("close_panel", {"panelId": panel_id})
        return {"closed": panel_id}

    return [show_panel, close_panel]
