"""Wires the core together: tool registry, MCP tool server, providers, router and brain."""

import logging
import secrets
from dataclasses import dataclass

from brain.brain import Brain
from brain.prompt import build_system_prompt
from brain.providers.base import Provider
from brain.providers.claude_cli import ClaudeCliProvider
from brain.router import Router
from config import Settings
from events import EventBus
from tools.mcp_server import McpToolServer
from tools.notes import make_notes_tools
from tools.registry import Confirmer, ToolRegistry
from tools.system import make_system_tools

log = logging.getLogger(__name__)


@dataclass
class Core:
    brain: Brain
    router: Router
    registry: ToolRegistry
    mcp: McpToolServer
    providers: list[Provider]
    events: EventBus

    async def close(self) -> None:
        await self.router.close()
        await self.mcp.stop()


async def start_core(settings: Settings, *, confirmer: Confirmer, events: EventBus) -> Core:
    registry = ToolRegistry(
        [*make_system_tools(), *make_notes_tools(settings.notes_dir)],
        confirmer=confirmer,
        confirm_timeout_s=settings.confirm_timeout_s,
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
                    system_prompt=build_system_prompt(settings.user_name),
                    mcp_config=mcp_config,
                    workdir=settings.data_dir / "work" / "claude",
                    tools_busy=lambda: registry.active_calls > 0,
                )
            )
        else:
            log.warning("provider %r is not built yet; skipping it", name)

    router = Router(providers, events)
    brain = Brain(router, registry, history_turns=settings.history_turns)
    return Core(brain, router, registry, mcp, providers, events)
