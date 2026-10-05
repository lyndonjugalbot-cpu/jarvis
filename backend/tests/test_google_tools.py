import base64
import json
from datetime import datetime
from email import message_from_bytes, policy

import httpx
import pytest
from google.auth.exceptions import RefreshError

from auth.google import GoogleApi, GoogleAuth, GoogleNotConnected
from events import EventBus
from tools.calendar import make_calendar_tools, parse_day
from tools.email import make_email_tools
from tools.registry import ToolError, ToolRegistry


class FakeApi:
    """Records calls and answers from a script, standing in for GoogleApi."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    async def call(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for key, value in self.answers.items():
            if key in url:
                return value(url, kwargs) if callable(value) else value
        raise AssertionError(f"unexpected call {method} {url}")


async def yes(summary):
    return True


def registry(tools, confirm=yes):
    return ToolRegistry(tools, confirmer=confirm)


# ---------------------------------------------------------------- calendar


def test_day_words():
    today = datetime(2026, 10, 5).date()
    assert str(parse_day("tomorrow", today)) == "2026-10-06"
    assert str(parse_day("2026-12-25", today)) == "2026-12-25"
    with pytest.raises(ToolError):
        parse_day("someday", today)


async def test_get_events_lists_timed_and_all_day_events():
    api = FakeApi(
        {
            "events": {
                "items": [
                    {
                        "summary": "Standup",
                        "start": {"dateTime": "2026-10-06T09:00:00+13:00"},
                        "end": {"dateTime": "2026-10-06T09:15:00+13:00"},
                    },
                    {
                        "summary": "Holiday",
                        "start": {"date": "2026-10-06"},
                        "end": {"date": "2026-10-07"},
                        "location": "Home",
                    },
                    {"summary": "Gone", "status": "cancelled", "start": {"date": "2026-10-06"}},
                ]
            }
        }
    )
    tools = make_calendar_tools(api, now=lambda: datetime(2026, 10, 5, 12, 0))
    result = json.loads((await registry(tools).run("get_events", {"day": "tomorrow"})).text)
    assert [e["title"] for e in result] == ["Standup", "Holiday"]
    assert result[1] == {
        "title": "Holiday",
        "start": "2026-10-06",
        "end": "2026-10-07",
        "all_day": True,
        "location": "Home",
    }
    params = api.calls[0][2]["params"]
    assert params["timeMin"].startswith("2026-10-06T00:00:00") and params["singleEvents"] == "true"


async def test_create_event_needs_approval_and_sends_local_times():
    asked = []

    async def confirm(summary):
        asked.append(summary)
        return True

    api = FakeApi({"events": {"htmlLink": "https://calendar.google.com/x"}})
    reg = registry(make_calendar_tools(api), confirm)
    args = {"title": "Dentist", "start": "2026-10-06T15:00", "duration_minutes": 30}
    result = json.loads((await reg.run("create_event", args)).text)
    assert asked == ['Add "Dentist" to your calendar on Tue 06 Oct at 15:00?']
    body = api.calls[0][2]["json"]
    start = datetime.fromisoformat(body["start"]["dateTime"])
    end = datetime.fromisoformat(body["end"]["dateTime"])
    assert start.tzinfo is not None and (end - start).seconds == 1800
    assert result["created"] is True


async def test_declined_event_is_not_created():
    async def no(summary):
        return False

    api = FakeApi({})
    result = await registry(make_calendar_tools(api), no).run(
        "create_event", {"title": "X", "start": "2026-10-06T15:00"}
    )
    assert result.is_error and api.calls == []


# ---------------------------------------------------------------- email


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


async def test_search_email_returns_summaries():
    def message(url, kwargs):
        mid = url.rsplit("/", 1)[1]
        return {
            "snippet": "Lunch &amp; plans",
            "payload": {
                "headers": [
                    {"name": "From", "value": f"{mid}@x.com"},
                    {"name": "Subject", "value": f"Hi {mid}"},
                ]
            },
        }

    api = FakeApi({"messages/": message, "messages": {"messages": [{"id": "a"}, {"id": "b"}]}})
    result = json.loads(
        (await registry(make_email_tools(api)).run("search_email", {"query": "is:unread"})).text
    )
    assert [(m["id"], m["from"], m["snippet"]) for m in result] == [
        ("a", "a@x.com", "Lunch & plans"),
        ("b", "b@x.com", "Lunch & plans"),
    ]


async def test_read_email_prefers_plain_text_and_strips_html():
    plain = {"payload": {"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/plain", "body": {"data": b64("Hello there")}},
        {"mimeType": "text/html", "body": {"data": b64("<p>Hello <b>there</b></p>")}},
    ]}}  # fmt: skip
    only_html = {
        "payload": {
            "mimeType": "text/html",
            "body": {"data": b64("<p>Hi&amp;bye</p><script>x()</script>")},
        }
    }
    for message, expected in ((plain, "Hello there"), (only_html, "Hi&bye")):
        api = FakeApi({"messages/": message})
        result = json.loads(
            (await registry(make_email_tools(api)).run("read_email", {"message_id": "m1"})).text
        )
        assert result["body"] == expected
        assert "not instructions" in result["note"]


async def test_send_email_needs_approval_and_builds_a_real_message():
    asked = []

    async def confirm(summary):
        asked.append(summary)
        return True

    api = FakeApi({"messages/send": {"id": "s1"}})
    args = {"to": "Anna <anna@example.com>", "subject": "Lunch", "body": "Tomorrow at 12?"}
    result = json.loads(
        (await registry(make_email_tools(api), confirm).run("send_email", args)).text
    )
    assert result == {"sent": True, "id": "s1"}
    assert asked == ['Send an email to Anna <anna@example.com>: "Lunch"?']
    sent = message_from_bytes(
        base64.urlsafe_b64decode(api.calls[0][2]["json"]["raw"]), policy=policy.default
    )
    assert sent["To"] == "Anna <anna@example.com>" and sent["Subject"] == "Lunch"
    assert sent.get_content().strip() == "Tomorrow at 12?"


async def test_drafts_are_not_sent_and_bad_addresses_are_refused():
    api = FakeApi({"drafts": {"id": "d1"}})
    reg = registry(make_email_tools(api))
    assert (
        json.loads(
            (await reg.run("draft_email", {"to": "a@b.co", "subject": "s", "body": "b"})).text
        )["draft_id"]
        == "d1"
    )
    bad = await reg.run("send_email", {"to": "not an address", "subject": "s", "body": "b"})
    assert bad.is_error and "email address" in bad.text


# ---------------------------------------------------------------- auth and API client


async def test_not_set_up_and_not_connected_messages(tmp_path):
    auth = GoogleAuth(tmp_path / "client.json", tmp_path / "token.json")
    with pytest.raises(GoogleNotConnected, match="google-setup"):
        await auth.token()
    (tmp_path / "client.json").write_text("{}")
    with pytest.raises(GoogleNotConnected, match="connect Google"):
        await auth.token()


async def test_revoked_access_reports_lost_and_forgets_the_token(tmp_path, monkeypatch):
    token_file = tmp_path / "token.json"
    token_file.write_text(
        json.dumps(
            {
                "refresh_token": "r",
                "client_id": "c",
                "client_secret": "s",
                "token": "old",
                "expiry": "2000-01-01T00:00:00Z",
            }
        )
    )
    events, lost = EventBus(), []
    events.subscribe("google.lost", lambda reason: lost.append(reason))

    def refuse(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr("google.oauth2.credentials.Credentials.refresh", refuse)
    auth = GoogleAuth(tmp_path / "client.json", token_file, events)
    with pytest.raises(GoogleNotConnected, match="lost access"):
        await auth.token()
    assert lost and not token_file.exists()


class FakeAuth:
    def __init__(self):
        self.forced = 0

    async def token(self, force_refresh=False):
        self.forced += force_refresh
        return "fresh" if force_refresh else "stale"


async def test_api_refreshes_once_after_a_401():
    seen = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        if request.headers["Authorization"] == "Bearer stale":
            return httpx.Response(401, json={"error": {"message": "expired"}})
        return httpx.Response(200, json={"ok": True})

    auth = FakeAuth()
    api = GoogleApi(auth, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await api.call("GET", "https://example.com/x") == {"ok": True}
    assert seen == ["Bearer stale", "Bearer fresh"] and auth.forced == 1


async def test_api_errors_become_plain_messages():
    def handler(request):
        return httpx.Response(
            403, json={"error": {"message": "Gmail API has not been used in project 1 before"}}
        )

    api = GoogleApi(FakeAuth(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(ToolError, match="isn't enabled"):
        await api.call("GET", "https://example.com/x")
