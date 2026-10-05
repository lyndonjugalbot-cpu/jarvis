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
        if "which part" in turn.text:
            return Reply(text=f"screen: {turn.screen}")
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
    app = create_app(
        settings,
        core_factory=fake_core,
        auth_timeout_s=0.3,
        voice_enabled=False,
        live_dashboard=False,
    )
    with TestClient(app) as c:
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
    assert session.receive_json()["type"] == "mic"
    telemetry = session.receive_json()
    assert telemetry["type"] == "telemetry" and 0 <= telemetry["payload"]["cpu"] <= 100
    modules = session.receive_json()
    assert modules["type"] == "modules"
    assert {"name": "Fake plan", "state": "online"} in modules["payload"]["rows"]
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


async def test_panel_types_are_checked():
    from tools.hud import make_hud_tools
    from tools.registry import ToolRegistry

    class Bridge:
        connected = True

        def __init__(self):
            self.sent = []

        async def broadcast(self, kind, payload):
            self.sent.append(payload["panel"])

    bridge = Bridge()
    reg = ToolRegistry(make_hud_tools(bridge))
    chart = {"labels": ["Mon", "Tue"], "values": ["3", 4.5], "unit": "km"}
    assert not (
        await reg.run("show_panel", {"title": "Runs", "type": "chart", "data": chart})
    ).is_error
    assert bridge.sent[-1]["data"] == {
        "labels": ["Mon", "Tue"],
        "values": [3.0, 4.5],
        "kind": "bar",
        "unit": "km",
    }
    events = [{"title": "Standup", "start": "Tue 09:00"}]
    assert not (
        await reg.run("show_panel", {"title": "Tomorrow", "type": "calendar", "data": events})
    ).is_error
    image = {"url": "https://example.com/cat.jpg", "caption": "Miso"}
    assert not (
        await reg.run("show_panel", {"title": "Cat", "type": "image", "data": image})
    ).is_error
    for bad in (
        {"type": "chart", "data": {"labels": ["a"], "values": [1, 2]}},
        {"type": "chart", "data": {"labels": ["a"], "values": ["x"]}},
        {"type": "calendar", "data": ["not an event"]},
        {"type": "image", "data": {"url": "file:///etc/passwd"}},
    ):
        result = await reg.run("show_panel", {"title": "x", **bad})
        assert result.is_error, bad


def test_avatar_is_served_when_present(client, tmp_path):
    assert client.get("/api/avatar").status_code == 404
    (tmp_path / "avatar.png").write_bytes(b"\x89PNG fake")
    response = client.get("/api/avatar")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"


async def test_files_panels_are_checked():
    from tools.hud import make_hud_tools
    from tools.registry import ToolRegistry

    class Bridge:
        connected = True
        sent = []

        async def broadcast(self, kind, payload):
            self.sent.append(payload["panel"])

    reg = ToolRegistry(make_hud_tools(Bridge()))
    rows = [
        {"name": "MSE800 - Assessment2", "path": "~/Documents/MSE800 - Assessment2", "folder": True}
    ]
    result = await reg.run("show_panel", {"title": "Files", "type": "files", "data": rows})
    assert not result.is_error
    assert Bridge.sent[-1]["data"] == {"folder": "", "files": rows}
    assert (await reg.run("show_panel", {"title": "x", "type": "files", "data": ["no"]})).is_error


async def test_models_are_found_and_shown(tmp_path):
    from tools.hud import make_hud_tools
    from tools.registry import ToolRegistry

    class Bridge:
        connected = True

        def __init__(self):
            self.sent = []

        async def broadcast(self, kind, payload):
            self.sent.append((kind, payload))

    (tmp_path / "robot_arm.glb").write_bytes(b"glTF")
    (tmp_path / "notes.txt").write_text("not a model")
    bridge = Bridge()
    reg = ToolRegistry(make_hud_tools(bridge, tmp_path))

    assert not (await reg.run("show_model", {"name": "jet engine"})).is_error
    assert bridge.sent[-1] == (
        "show_model",
        {"id": "jet-engine", "title": "Jet engine", "explode": 0},
    )
    await reg.run("show_model", {"name": "engine", "explode": 1})  # close enough, broken apart
    assert bridge.sent[-1][1]["id"] == "jet-engine" and bridge.sent[-1][1]["explode"] == 1
    await reg.run("show_model", {"name": "Robot arm"})
    assert bridge.sent[-1][1] == {
        "id": "file:robot_arm.glb",
        "title": "robot arm",
        "file": "robot_arm.glb",
        "explode": 0,
    }
    missing = await reg.run("show_model", {"name": "notes"})
    assert missing.is_error and "Quadcopter drone" in missing.text and "robot arm" in missing.text
    assert not (await reg.run("close_model", {})).is_error
    assert bridge.sent[-1] == ("close_model", {})

    bridge.connected = False
    result = await reg.run("show_model", {"name": "drone"})
    assert not result.is_error and "no hud is connected" in result.text.lower()


def test_hologram_files_are_served(client, tmp_path):
    listed = client.get("/api/holograms").json()["models"]
    assert [m["id"] for m in listed] == ["jet-engine", "drone", "arc-reactor"]
    folder = tmp_path / "holograms"
    folder.mkdir()
    (folder / "robot.glb").write_bytes(b"glTF binary")
    (folder / ".secret.glb").write_bytes(b"hidden")
    (folder / "notes.txt").write_text("no")
    (tmp_path / "outside.glb").write_bytes(b"outside")
    assert {"id": "file:robot.glb", "title": "robot", "file": "robot.glb"} in client.get(
        "/api/holograms"
    ).json()["models"]
    assert client.get("/api/holograms/robot.glb").content == b"glTF binary"
    for bad in (".secret.glb", "notes.txt", "missing.glb", "..%2Foutside.glb", "%2E%2E"):
        assert client.get(f"/api/holograms/{bad}").status_code == 404, bad


def test_the_selected_part_reaches_the_brain(client):
    ws, session = connect(client)
    state = {"model": "Jet engine", "part": "High-pressure turbine", "explode": 1}
    session.send_json({"type": "model_state", "payload": state, "id": "h2"})
    session.send_json({"type": "user_text", "payload": {"text": "which part is this?"}, "id": "h3"})
    replies = [
        m["payload"]["text"]
        for m in until_idle(session)
        if m["type"] == "transcript" and m["payload"]["role"] == "jarvis"
    ]
    ws.__exit__(None, None, None)
    assert replies == [
        "screen: a holographic Jet engine model, broken apart into its parts; "
        "the user has selected its part: High-pressure turbine."
    ]


def test_screen_context_is_part_of_the_prompt():
    from brain.providers.base import compose

    prompt = compose(Turn(id="t", text="what is it?", screen="a holographic drone model."))
    assert prompt.endswith(
        "On the HUD right now: a holographic drone model.\n\nNew message:\nwhat is it?"
    )
    assert compose(Turn(id="t", text="hi")) == "hi"
