"""Serves the tool registry over MCP (streamable HTTP) on 127.0.0.1 for the CLI providers.

Tools run inside the JARVIS process, so confirmation and the per-turn call log apply no
matter which provider made the call. Every request needs the bearer token.
"""

import asyncio
import contextlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

import uvicorn
from mcp import types
from mcp.server import Server
from starlette.responses import JSONResponse

from tools.registry import ToolRegistry

SERVER_NAME = "jarvis"


class _QuietServer(uvicorn.Server):
    """A uvicorn server that leaves Ctrl+C to the host app."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield


class _BearerAuth:
    def __init__(self, app: Any, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            given = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(given, self._expected):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self._app(scope, receive, send)


def build_mcp_app(registry: ToolRegistry, token: str) -> Any:
    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(name=s.name, description=s.description, input_schema=s.input_schema)
                for s in registry.specs()
            ]
        )

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        result = await registry.run(params.name, params.arguments)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=result.text)], is_error=result.is_error
        )

    server = Server(
        SERVER_NAME, version="0.1.0", on_list_tools=on_list_tools, on_call_tool=on_call_tool
    )
    app = server.streamable_http_app(stateless_http=True, json_response=True, host="127.0.0.1")
    return _BearerAuth(app, token)


class McpToolServer:
    """Runs the MCP app on a free local port for as long as the core is up."""

    def __init__(self, registry: ToolRegistry, token: str, host: str = "127.0.0.1") -> None:
        if not token:
            raise ValueError("the MCP tool server needs a token")
        self._token = token
        self._server = _QuietServer(
            uvicorn.Config(build_mcp_app(registry, token), host=host, port=0, log_level="warning")
        )
        self._task: asyncio.Task | None = None
        self.url = ""

    async def start(self) -> None:
        self._task = asyncio.create_task(self._server.serve())
        while not self._server.started:
            if self._task.done():
                self._task.result()  # surfaces the startup error
            await asyncio.sleep(0.02)
        host, port = self._server.servers[0].sockets[0].getsockname()[:2]
        self.url = f"http://{host}:{port}/mcp"

    async def stop(self) -> None:
        if self._task:
            self._server.should_exit = True
            await self._task

    def client_config(self) -> dict:
        """The server entry for a CLI's MCP config."""
        return {
            "type": "http",
            "url": self.url,
            "headers": {"Authorization": f"Bearer {self._token}"},
        }

    def write_claude_config(self, path: Path) -> Path:
        """Write an --mcp-config file for Claude Code, readable only by this user."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"mcpServers": {SERVER_NAME: self.client_config()}}, f, indent=2)
        return path
