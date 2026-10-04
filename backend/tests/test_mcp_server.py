import json

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from tools.mcp_server import McpToolServer
from tools.notes import make_notes_tools
from tools.registry import ToolRegistry
from tools.system import make_system_tools

TOKEN = "test-token"


@pytest.fixture
async def server(tmp_path):
    async def yes(summary: str) -> bool:
        return True

    registry = ToolRegistry([*make_system_tools(), *make_notes_tools(tmp_path)], confirmer=yes)
    srv = McpToolServer(registry, token=TOKEN)
    await srv.start()
    yield srv
    await srv.stop()


def client(url: str, token: str = TOKEN) -> Client:
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})
    return Client(streamable_http_client(url, http_client=http))


async def test_lists_and_calls_registry_tools(server):
    async with client(server.url) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert set(tools) == {"get_time", "write_note", "list_notes", "read_note"}
        assert tools["write_note"].input_schema["required"] == ["title", "text"]

        result = await c.call_tool("get_time", {})
        assert not result.is_error
        assert "timezone" in json.loads(result.content[0].text)

        missing = await c.call_tool("read_note", {"title": "nope"})
        assert missing.is_error


async def test_rejects_requests_without_the_token(server):
    async with httpx2.AsyncClient() as http:
        response = await http.post(server.url, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert response.status_code == 401


def test_claude_config_file_is_private(server, tmp_path):
    path = server.write_claude_config(tmp_path / "run" / "claude-mcp.json")
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    entry = json.loads(path.read_text())["mcpServers"]["jarvis"]
    assert entry == {
        "type": "http",
        "url": server.url,
        "headers": {"Authorization": f"Bearer {TOKEN}"},
    }
