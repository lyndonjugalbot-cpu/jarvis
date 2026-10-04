"""System tools: time now; apps, URLs and CPU/RAM/battery in Phase 4."""

from datetime import datetime

from tools.registry import ToolSpec, tool


def make_system_tools() -> list[ToolSpec]:
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

    return [get_time]
