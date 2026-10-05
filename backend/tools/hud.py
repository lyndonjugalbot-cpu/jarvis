"""HUD tools: put information on screen as panels, and holographic models on the stage."""

import re
import secrets
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import Field

from tools.registry import ToolError, ToolSpec, tool

CHART_KINDS = ("bar", "line")

# Built-in holograms, drawn by the HUD (frontend/src/hud/holograms/builtins.js uses these ids).
BUILTIN_MODELS = {
    "jet-engine": "Jet engine",
    "drone": "Quadcopter drone",
    "arc-reactor": "Arc reactor",
}
MODEL_FILES = (".glb", ".gltf")
# What a model folder may serve: the models plus a .gltf file's buffers and textures.
MODEL_ASSETS = (*MODEL_FILES, ".bin", ".png", ".jpg", ".jpeg", ".webp")


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def available_models(folder: Path | None) -> list[dict]:
    """The built-in models, then the user's .glb/.gltf files in `folder` (~/.jarvis/holograms)."""
    models = [{"id": key, "title": title} for key, title in BUILTIN_MODELS.items()]
    if folder is not None and folder.is_dir():
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() in MODEL_FILES and not path.name.startswith("."):
                title = re.sub(r"[_-]+", " ", path.stem).strip() or path.name
                models.append({"id": f"file:{path.name}", "title": title, "file": path.name})
    return models


def find_model(name: str, folder: Path | None) -> dict | None:
    key = _key(name)
    if not key:
        return None
    models = available_models(folder)
    for model in models:
        if key in (_key(model["id"]), _key(model["title"]), _key(model.get("file", ""))):
            return model
    close = [m for m in models if key in _key(m["title"])]  # "engine" finds "Jet engine"
    return close[0] if len(close) == 1 else None


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


def make_hud_tools(bridge: Any, holograms: Path | None = None) -> list[ToolSpec]:
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

    @tool()
    async def show_model(
        name: Annotated[str, Field(description="Which model, for example 'jet engine'")],
        explode: Annotated[
            float, Field(ge=0, le=1, description="0 assembled, 1 fully broken apart")
        ] = 0,
    ) -> dict:
        """Show a 3D holographic model on the HUD's stage, to explore how something is put
        together. Built in: jet engine, quadcopter drone, arc reactor; plus the user's own .glb
        or .gltf files in ~/.jarvis/holograms. The user turns it with a pinch-drag, breaks it
        apart by spreading two hands (or set `explode`), and pinches a part to see what it is."""
        if not bridge.connected:
            return {"shown": False, "reason": "No HUD is connected, so describe it in words."}
        model = find_model(name, holograms)
        if model is None:
            names = ", ".join(m["title"] for m in available_models(holograms))
            raise ToolError(f"There's no model called {name!r}. Available: {names}")
        await bridge.broadcast("show_model", {**model, "explode": explode})
        return {"shown": True, "model": model["title"]}

    @tool()
    async def close_model() -> dict:
        """Put the holographic model away; the stage shows JARVIS again."""
        await bridge.broadcast("close_model", {})
        return {"closed": True}

    return [show_panel, close_panel, show_model, close_model]
