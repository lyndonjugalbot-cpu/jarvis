"""File tools: find files (Spotlight on macOS) and read text files, only inside the allowed
folders (`[tools] file_roots` in config.toml: Documents, Desktop and Downloads by default)."""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

from pydantic import Field

from tools.registry import ToolError, ToolSpec, tool

MAX_RESULTS = 20
MAX_CANDIDATES = 300
MAX_CHARS = 20_000
MAX_BYTES = 1_000_000
WALK_DIR_LIMIT = 5000


def _hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


async def _spotlight(query: str, roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        proc = await asyncio.create_subprocess_exec(
            "mdfind", "-onlyin", str(root), query,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 10)
        except TimeoutError:
            proc.kill()
            continue
        found += [Path(line) for line in out.decode(errors="replace").splitlines() if line]
    return found


def _walk(query: str, roots: list[Path]) -> list[Path]:
    """Filename search for systems without Spotlight."""
    words = query.lower().split()
    found: list[Path] = []
    visited = 0
    for root in roots:
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            visited += 1
            for name in files:
                if all(w in name.lower() for w in words):
                    found.append(Path(folder) / name)
            if len(found) >= MAX_CANDIDATES or visited >= WALK_DIR_LIMIT:
                return found
    return found


def make_file_tools(
    roots: list[Path], *, spotlight: bool = sys.platform == "darwin"
) -> list[ToolSpec]:
    roots = [r.expanduser().resolve() for r in roots if r.expanduser().exists()]
    home = Path.home()

    def show(path: Path) -> str:
        return f"~/{path.relative_to(home)}" if path.is_relative_to(home) else str(path)

    def inside_roots(path: str) -> Path:
        real = Path(path).expanduser().resolve()  # follows symlinks, so they can't escape
        if _hidden(real) or not any(real.is_relative_to(r) for r in roots):
            allowed = ", ".join(show(r) for r in roots) or "none"
            raise ToolError(f"I can only read files in these folders: {allowed}.")
        return real

    @tool()
    async def search_files(
        query: Annotated[str, Field(description="Words from the file's name or contents")],
    ) -> list[dict]:
        """Find files by name or contents in the allowed folders. Newest first."""
        if not query.strip():
            raise ToolError("Tell me what to look for.")
        candidates = (
            await _spotlight(query, roots)
            if spotlight
            else await asyncio.to_thread(_walk, query, roots)
        )
        results = []
        for path in candidates[:MAX_CANDIDATES]:
            if _hidden(path):
                continue
            try:
                info = path.stat()
            except OSError:
                continue
            results.append(
                {
                    "path": show(path),
                    "name": path.name,
                    "modified": datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "size_kb": round(info.st_size / 1024, 1),
                    "folder": path.is_dir(),
                }
            )
        results.sort(key=lambda r: r["modified"], reverse=True)
        return results[:MAX_RESULTS]

    @tool()
    async def read_file(
        path: Annotated[str, Field(description="A path from search_files")],
    ) -> dict:
        """Read a text file from the allowed folders. Long files are cut short."""
        real = inside_roots(path)
        if real.is_dir():
            raise ToolError("That's a folder. Use search_files to find a file inside it.")
        if not real.is_file():
            raise ToolError("There's no file at that path.")

        def read() -> bytes:
            with real.open("rb") as f:
                return f.read(MAX_BYTES)

        raw = await asyncio.to_thread(read)
        if b"\x00" in raw[:4096]:
            raise ToolError("That isn't a plain text file, so I can't read it yet.")
        text = raw.decode("utf-8", errors="replace")
        return {
            "path": show(real),
            "text": text[:MAX_CHARS],
            "truncated": len(text) > MAX_CHARS or len(raw) == MAX_BYTES,
        }

    return [search_files, read_file]
