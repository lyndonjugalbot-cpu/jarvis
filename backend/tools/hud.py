"""HUD tools: put information on screen as floating panels."""

import secrets
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import Field

from tools.registry import ToolError, ToolSpec, tool

CHART_KINDS = ("bar", "line")


def _check(kind: str, data: Any) -> Any:
    """Each panel type's data shape; a clear error helps the model fix its call."""
    if kind == "text":
        return "\n".join(map(str, data)) if isinstance(data, list) else str(data)
    if kind == "list":
        if isinstance(data, str):
            return [line.strip() for line in data.splitlines() if line.strip()]
        return [str(item) for item in data] if isinstance(data, list) else [str(data)]
    if kind == "calendar":
        events = data if isinstance(data, list) else None
        if not events or not all(isinstance(e, dict) and e.get("title") for e in events):
            raise ToolError('calendar data is a list of {"title", "start", "end", "location"}')
        return events
    if kind == "chart":
        ok = isinstance(data, dict) and isinstance(data.get("labels"), list)
        values = data.get("values") if ok else None
        if not ok or not isinstance(values, list) or len(values) != len(data["labels"]):
            raise ToolError(
                'chart data is {"labels": [...], "values": [numbers], "kind": "bar"|"line"}'
            )
        try:
            numbers = [float(v) for v in values]
        except (TypeError, ValueError):
            raise ToolError("chart values must be numbers") from None
        return {
            "labels": [str(label) for label in data["labels"]],
            "values": numbers,
            "kind": data.get("kind") if data.get("kind") in CHART_KINDS else "bar",
            "unit": str(data.get("unit", "")),
        }
    if kind == "files":
        rows = data.get("files") if isinstance(data, dict) else data
        if not isinstance(rows, list) or not all(
            isinstance(r, dict) and r.get("name") for r in rows
        ):
            raise ToolError('files data is [{"name", "path", "modified", "size_kb", "folder"}]')
        folder = data.get("folder", "") if isinstance(data, dict) else ""
        return {"folder": str(folder), "files": rows}
    if kind == "image":
        url = data.get("url", "") if isinstance(data, dict) else str(data)
        if urlparse(url).scheme not in ("http", "https"):
            raise ToolError('image data is {"url": "https://...", "caption": ""}')
        caption = data.get("caption", "") if isinstance(data, dict) else ""
        return {"url": url, "caption": str(caption)}
    raise ToolError(f"unknown panel type {kind!r}")


def make_hud_tools(bridge: Any) -> list[ToolSpec]:
    @tool()
    async def show_panel(
        title: Annotated[str, Field(description="Short panel title")],
        data: Annotated[
            str | list[str] | list[dict] | dict,
            Field(
                description=(
                    "text: a string. list: short lines. "
                    'calendar: [{"title", "start", "end", "location"}]. '
                    'chart: {"labels": [...], "values": [numbers], '
                    '"kind": "bar"|"line", "unit": ""}. '
                    'image: {"url": "https://...", "caption": ""}. '
                    'files: search_files results as they are, or {"folder", "files": [...]}'
                )
            ),
        ],
        type: Annotated[
            Literal["text", "list", "calendar", "chart", "image", "files"],
            Field(description="Panel type"),
        ] = "text",
        panel_id: Annotated[
            str, Field(description="An id from an earlier show_panel, to update that panel")
        ] = "",
    ) -> dict:
        """Show information on the HUD as a floating panel: lists, notes, events, numbers to
        compare, pictures, anything worth reading. Keep the spoken reply short and point to it."""
        if not bridge.connected:
            return {"shown": False, "reason": "No HUD is connected, so answer in words instead."}
        data = _check(type, data)
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
