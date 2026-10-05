"""Calendar tools: read and add events in the user's primary Google Calendar."""

from datetime import date, datetime, time, timedelta
from typing import Annotated, Any

from pydantic import Field

from tools.registry import ToolError, ToolSpec, tool

EVENTS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def parse_day(day: str, today: date) -> date:
    d = day.strip().lower()
    if d in ("", "today"):
        return today
    if d == "tomorrow":
        return today + timedelta(days=1)
    if d == "yesterday":
        return today - timedelta(days=1)
    try:
        return date.fromisoformat(d)
    except ValueError:
        raise ToolError(
            f'Use "today", "tomorrow" or a date like 2026-10-06, not "{day}".'
        ) from None


def local_datetime(value: str) -> datetime:
    """An ISO date-time; without a UTC offset it means local time."""
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        raise ToolError(
            f'Use a local date and time like 2026-10-06T15:00, not "{value}".'
        ) from None
    return dt if dt.tzinfo else dt.astimezone()


def _when(value: dict) -> str:
    if "dateTime" in value:
        return datetime.fromisoformat(value["dateTime"]).astimezone().strftime("%a %d %b %H:%M")
    return value.get("date", "")


def _event(item: dict) -> dict:
    event = {
        "title": item.get("summary", "(no title)"),
        "start": _when(item.get("start", {})),
        "end": _when(item.get("end", {})),
        "all_day": "date" in item.get("start", {}),
    }
    if item.get("location"):
        event["location"] = item["location"]
    return event


def _create_summary(args: dict) -> str:
    try:
        when = local_datetime(args["start"]).strftime("%a %d %b at %H:%M")
    except ToolError:
        when = args["start"]
    return f'Add "{args["title"]}" to your calendar on {when}?'


def make_calendar_tools(api: Any, now=datetime.now) -> list[ToolSpec]:
    @tool()
    async def get_events(
        day: Annotated[str, Field(description='"today", "tomorrow" or YYYY-MM-DD')] = "today",
        days: Annotated[int, Field(ge=1, le=14, description="How many days from that day")] = 1,
    ) -> list[dict]:
        """Return calendar events for a day ("today", "tomorrow" or YYYY-MM-DD), or several days."""
        start = datetime.combine(parse_day(day, now().date()), time.min).astimezone()
        params = {
            "timeMin": start.isoformat(),
            "timeMax": (start + timedelta(days=days)).isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 100,
        }
        data = await api.call("GET", EVENTS, params=params)
        return [_event(item) for item in data.get("items", []) if item.get("status") != "cancelled"]

    @tool(confirm=True, summary=_create_summary)
    async def create_event(
        title: Annotated[str, Field(description="What the event is")],
        start: Annotated[str, Field(description="Local start, e.g. 2026-10-06T15:00")],
        duration_minutes: Annotated[int, Field(ge=5, le=1440)] = 60,
        location: str = "",
        description: str = "",
    ) -> dict:
        """Add an event to the calendar. Call get_time first if the date is relative."""
        begin = local_datetime(start)
        body: dict = {
            "summary": title,
            "start": {"dateTime": begin.isoformat()},
            "end": {"dateTime": (begin + timedelta(minutes=duration_minutes)).isoformat()},
        }
        if location:
            body["location"] = location
        if description:
            body["description"] = description
        created = await api.call("POST", EVENTS, json=body)
        return {
            "created": True,
            "title": title,
            "start": begin.strftime("%a %d %b %H:%M"),
            "link": created.get("htmlLink", ""),
        }

    return [get_events, create_event]
