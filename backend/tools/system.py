"""System tools: the time, CPU/RAM/disk/battery, and opening apps and web pages."""

import asyncio
import sys
import time
import webbrowser
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated
from urllib.parse import urlparse

import psutil
from pydantic import Field

from tools.registry import ToolError, ToolSpec, tool

Runner = Callable[[list[str]], Awaitable[int]]


async def run(args: list[str]) -> int:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    return await proc.wait()


def make_system_tools(*, runner: Runner = run, platform: str = sys.platform) -> list[ToolSpec]:
    @tool()
    async def get_time() -> dict:
        """Return the current local date, time, weekday and timezone."""
        now = datetime.now().astimezone()
        return {
            "date": now.strftime("%A %d %B %Y"),
            "time": now.strftime("%H:%M"),
            "timezone": now.tzname(),
            "utc_offset": now.strftime("%z"),
            "iso": now.isoformat(timespec="seconds"),
        }

    @tool()
    async def system_stats() -> dict:
        """CPU and memory use, free disk space, battery and uptime of this computer."""
        cpu = await asyncio.to_thread(psutil.cpu_percent, 0.3)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        battery = psutil.sensors_battery()
        return {
            "cpu_pct": cpu,
            "memory_used_pct": memory.percent,
            "memory_available_gb": round(memory.available / 1e9, 1),
            "disk_free_gb": round(disk.free / 1e9, 1),
            "battery_pct": round(battery.percent) if battery else None,
            "charging": battery.power_plugged if battery else None,
            "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 1),
        }

    @tool()
    async def open_app(
        name: Annotated[str, Field(description='The app\'s name, e.g. "Safari" or "Calendar"')],
    ) -> dict:
        """Open an app on this Mac."""
        if platform != "darwin":
            raise ToolError("Opening apps only works on macOS for now.")
        if not name.strip() or name.startswith("-"):
            raise ToolError("Tell me which app to open.")
        if await runner(["open", "-a", name.strip()]) != 0:
            raise ToolError(f'I couldn\'t find an app called "{name}".')
        return {"opened": name.strip()}

    @tool()
    async def open_url(
        url: Annotated[str, Field(description="An http or https web address")],
    ) -> dict:
        """Open a web page in the default browser."""
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ToolError("I can only open http and https web addresses.")
        if platform == "darwin":
            if await runner(["open", url.strip()]) != 0:
                raise ToolError("The browser didn't open that address.")
        else:
            await asyncio.to_thread(webbrowser.open, url.strip())
        return {"opened": url.strip()}

    return [get_time, system_stats, open_app, open_url]
