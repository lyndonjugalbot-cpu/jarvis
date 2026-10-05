"""Wires the core together: tool registry, MCP tool server, providers, router and brain."""

import logging
import secrets
from dataclasses import dataclass
from typing import Any

from auth.google import GoogleApi, GoogleAuth
from brain.brain import Brain
from brain.prompt import build_system_prompt
from brain.providers.base import Provider
from brain.providers.claude_cli import ClaudeCliProvider
from brain.router import Router
from config import Settings
from events import EventBus
from tools.calendar import make_calendar_tools
from tools.email import make_email_tools
from tools.files import make_file_tools
from tools.google_account import make_google_account_tools
from tools.hud import make_hud_tools
from tools.mcp_server import McpToolServer
from tools.notes import make_notes_tools
from tools.registry import Confirmer, ToolRegistry
from tools.system import make_system_tools
from tools.weather import home_place, make_weather_tools

log = logging.getLogger(__name__)


@dataclass
class Core:
    brain: Brain
    router: Router
    registry: ToolRegistry
    mcp: McpToolServer | None
    providers: list[Provider]
    events: EventBus
    google: GoogleAuth | None = None
    google_api: GoogleApi | None = None

    async def close(self) -> None:
        await self.router.close()
        if self.mcp:
            await self.mcp.stop()
        if self.google_api:
            await self.google_api.close()


async def start_core(
    settings: Settings, *, confirmer: Confirmer, events: EventBus, hud: Any = None
) -> Core:
    """Start the brain. `hud` (a HudBridge) adds the screen tools; the terminal chat has none."""
    google = GoogleAuth(settings.google_client_file, settings.google_token_file, events)
    google_api = GoogleApi(google)
    tools = [
        *make_system_tools(),
        *make_notes_tools(settings.notes_dir),
        *make_file_tools(list(settings.file_roots)),
        *make_weather_tools(home_place(settings.location)),
        *make_calendar_tools(google_api),
        *make_email_tools(google_api),
        *make_google_account_tools(google),
    ]
    if hud is not None:
        tools += make_hud_tools(hud)
    registry = ToolRegistry(
        tools, confirmer=confirmer, confirm_timeout_s=settings.confirm_timeout_s
    )
    mcp = McpToolServer(registry, token=secrets.token_urlsafe(32))  # fresh token every run
    await mcp.start()
    mcp_config = mcp.write_claude_config(settings.run_dir / "claude-mcp.json")

    providers: list[Provider] = []
    for name in settings.provider_order:
        if name == "claude_plan":
            providers.append(
                ClaudeCliProvider(
                    settings.claude_plan,
                    system_prompt=build_system_prompt(settings.user_name, hud=hud is not None),
                    mcp_config=mcp_config,
                    workdir=settings.data_dir / "work" / "claude",
                    tools_busy=lambda: registry.active_calls > 0,
                )
            )
        else:
            log.warning("provider %r is not built yet; skipping it", name)

    router = Router(providers, events)
    brain = Brain(router, registry, history_turns=settings.history_turns)
    return Core(brain, router, registry, mcp, providers, events, google, google_api)
