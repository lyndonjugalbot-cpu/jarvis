import asyncio
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from brain.brain import Brain
from brain.providers.base import ProviderLimitError, Reply, Turn
from brain.router import Router
from config import load_settings
from core import Core
from hud_bridge import HudBridge
from main import create_app
from tools.hud import make_hud_tools
from tools.notes import make_notes_tools
from tools.registry import ToolRegistry

ORIGIN = {"origin": "http://127.0.0.1:5173"}
TOKEN = "test-token"


class ScriptedProvider:
    """Stands in for the model: calls tools the way a model would, based on the request text."""

    name = "fake_plan"
    label = "Fake plan"

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def available(self) -> bool:
        return True

    async def send(self, turn: Turn) -> Reply:
        if "note" in turn.text:
            result = await self.registry.run("write_note", {"title": "Groceries", "text": "milk"})
            return Reply(text=f"note result: {result.text}")
        if "panel" in turn.text:
            await self.registry.run(
                "show_panel", {"title": "Notes", "data": ["a", "b"], "type": "list"}
            )
            return Reply(text="It's on screen.")
        if "limit" in turn.text:
            raise ProviderLimitError("limit", reset_at=4102444800)  # 2100-01-01
        return Reply(text=f"echo: {turn.text}")

    async def close(self) -> None:
        pass


async def fake_core(settings, *, confirmer, events, hud=None):
    registry = ToolRegistry(
        [*make_notes_tools(settings.notes_dir), *make_hud_tools(hud)],
        confirmer=confirmer,
        confirm_timeout_s=settings.confirm_timeout_s,
    )
    provider = ScriptedProvider(registry)
    router = Router([provider], events)
    return Core(Brain(router, registry), router, registry, None, [provider], events)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    settings = replace(
        load_settings(tmp_path / "none.toml", tmp_path / "none.env"),
        token=TOKEN,
        notes_dir=tmp_path / "notes",
        confirm_timeout_s=2,
    )
    with TestClient(create_app(settings, core_factory=fake_core, auth_timeout_s=0.3)) as c:
        yield c


def connect(client):
    ws = client.websocket_connect("/ws", headers=ORIGIN)
    session = ws.__enter__()
    session.send_json({"type": "auth", "payload": {"token": TOKEN}, "id": "h1"})
    assert session.receive_json()["type"] == "auth_ok"
    provider = session.receive_json()
    assert provider["type"] == "provider"
    assert provider["payload"]["order"] == ["Fake plan"]
    assert session.receive_json()["payload"] == {"state": "idle"}
    return ws, session


def until_idle(session):
    """Collect messages until the turn ends (state goes back to idle)."""
    messages = []
    while True:
        message = session.receive_json()
        messages.append(message)
        if message["type"] == "state" and message["payload"]["state"] == "idle":
            return messages


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_other_websites_are_refused(client):
    with pytest.raises(WebSocketDisconnect) as err:
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}):
            pass
    assert err.value.code == 4403


def test_token_must_come_first_and_match(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        with pytest.raises(WebSocketDisconnect) as err:
            ws.receive_json()  # nothing sent: closed after the auth timeout
        assert err.value.code == 4401
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.send_json({"type": "auth", "payload": {"token": "wrong"}})
        with pytest.raises(WebSocketDisconnect) as err:
            ws.receive_json()
        assert err.value.code == 4401
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.send_json({"type": "user_text", "payload": {"text": "hi"}})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_typed_request_round_trip(client):
    ws, session = connect(client)
    session.send_json({"type": "user_text", "payload": {"text": "hello"}, "id": "h2"})
    messages = until_idle(session)
    kinds = [m["type"] for m in messages]
    assert kinds[:2] == ["transcript", "state"]
    assert messages[0]["payload"] == {"role": "user", "text": "hello"}
    assert messages[1]["payload"] == {"state": "thinking"}
    reply = next(
        m["payload"]
        for m in messages
        if m["type"] == "transcript" and m["payload"]["role"] == "jarvis"
    )
    assert reply["text"] == "echo: hello" and reply["provider"] == "fake_plan"
    provider = next(m["payload"] for m in messages if m["type"] == "provider")
    assert (provider["active"], provider["label"], provider["paid"]) == (
        "fake_plan",
        "Fake plan",
        False,
    )
    ws.__exit__(None, None, None)


def test_show_panel_reaches_the_hud(client):
    ws, session = connect(client)
    session.send_json({"type": "user_text", "payload": {"text": "panel please"}})
    messages = until_idle(session)
    panel = next(m["payload"]["panel"] for m in messages if m["type"] == "show_panel")
    assert panel["type"] == "list" and panel["data"] == ["a", "b"] and panel["id"].startswith("p")
    ws.__exit__(None, None, None)


@pytest.mark.parametrize("approved", [True, False])
def test_confirmation_by_the_hud(client, tmp_path, approved):
    ws, session = connect(client)
    session.send_json({"type": "user_text", "payload": {"text": "save a note"}})
    request = None
    while request is None:
        message = session.receive_json()
        if message["type"] == "confirm_request":
            request = message["payload"]
    assert request["summary"] == 'Save a note titled "Groceries"?'
    session.send_json(
        {"type": "confirm", "payload": {"actionId": request["actionId"], "approved": approved}}
    )
    messages = until_idle(session)
    done = next(m["payload"] for m in messages if m["type"] == "confirm_done")
    assert done == {"actionId": request["actionId"], "approved": approved}
    assert (tmp_path / "notes" / "groceries.md").exists() is approved
    ws.__exit__(None, None, None)


def test_provider_limit_is_reported(client):
    ws, session = connect(client)
    session.send_json({"type": "user_text", "payload": {"text": "limit"}})
    messages = until_idle(session)
    error = next(m["payload"] for m in messages if m["type"] == "error")
    assert "can't answer" in error["message"] and "back at" in error["message"]
    ws.__exit__(None, None, None)


def test_bad_messages_get_an_error_and_the_socket_stays_open(client):
    ws, session = connect(client)
    session.send_text("not json")
    assert session.receive_json()["type"] == "error"
    session.send_json({"type": "mystery"})
    assert "Unknown" in session.receive_json()["payload"]["message"]
    session.send_json({"type": "user_text", "payload": {"text": "still here?"}})
    assert any(m["type"] == "transcript" for m in until_idle(session))
    ws.__exit__(None, None, None)


async def test_confirm_without_a_hud_is_no():
    assert await HudBridge().confirm("Do it?") is False


async def test_confirm_is_resolved_once():
    bridge = HudBridge()

    class Client:
        def __init__(self):
            self.sent = []

        async def send_json(self, data):
            self.sent.append(data)

    hud = Client()
    bridge.add(hud)
    waiting = asyncio.create_task(bridge.confirm("Do it?"))
    await asyncio.sleep(0)
    action_id = hud.sent[0]["payload"]["actionId"]
    assert bridge.resolve(action_id, True) is True
    assert bridge.resolve(action_id, False) is False  # a second HUD answering late changes nothing
    assert await waiting is True
