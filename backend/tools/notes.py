"""Notes: Markdown files in the notes folder (~/.jarvis/notes by default)."""

import re
from datetime import datetime
from pathlib import Path
from typing import Annotated

from pydantic import Field

from tools.registry import ToolError, ToolSpec, tool

MAX_LISTED = 20
PREVIEW_CHARS = 120


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:80] or "untitled"


def make_notes_tools(notes_dir: Path, on_saved=None) -> list[ToolSpec]:
    """`on_saved(title, text)`, if given, is awaited after a note is written (memory indexes it)."""

    def path_for(title: str) -> Path:
        return notes_dir / f"{slugify(title)}.md"

    @tool(confirm=True, summary=lambda a: f'Save a note titled "{a["title"]}"?')
    async def write_note(
        title: Annotated[str, Field(description="Short title; the same title adds to that note")],
        text: Annotated[str, Field(description="The note's content")],
    ) -> dict:
        """Save a note. If a note with this title exists, the text is added to the end of it."""
        notes_dir.mkdir(parents=True, exist_ok=True)
        path = path_for(title)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        existed = path.exists()
        if existed:
            with path.open("a", encoding="utf-8") as f:
                f.write(f"\n\n_{stamp}_\n\n{text.strip()}\n")
        else:
            path.write_text(f"# {title.strip()}\n\n_{stamp}_\n\n{text.strip()}\n", encoding="utf-8")
        if on_saved:
            await on_saved(title.strip(), path.read_text(encoding="utf-8"))
        return {"saved": path.name, "added_to_existing": existed}

    @tool()
    async def list_notes(
        query: Annotated[str, Field(description="Only notes containing this text")] = "",
    ) -> list[dict]:
        """List saved notes, newest first, with a short preview of each."""
        if not notes_dir.exists():
            return []
        found = []
        for path in sorted(notes_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            body = path.read_text(encoding="utf-8")
            if query and query.lower() not in body.lower():
                continue
            lines = body.splitlines()
            title = lines[0].lstrip("# ").strip() if lines else path.stem
            preview = " ".join(line for line in lines[1:] if line and not line.startswith("_"))
            found.append(
                {
                    "title": title,
                    "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime(
                        "%Y-%m-%d %H:%M"
                    ),
                    "preview": preview[:PREVIEW_CHARS],
                }
            )
            if len(found) == MAX_LISTED:
                break
        return found

    @tool()
    async def read_note(
        title: Annotated[str, Field(description="The note's title")],
    ) -> str:
        """Return the full text of a saved note."""
        path = path_for(title)
        if not path.exists():
            raise ToolError(f'No note titled "{title}". Use list_notes to see saved notes.')
        return path.read_text(encoding="utf-8")

    return [write_note, list_notes, read_note]
