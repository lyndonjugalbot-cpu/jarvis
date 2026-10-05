"""Settings for the JARVIS core, loaded from config.toml and .env."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ClaudePlanSettings:
    """Claude subscription provider: the official Claude Code CLI in headless mode."""

    enabled: bool = True
    command: str = "claude"
    model: str = ""  # empty = the CLI's default model
    effort: str = ""  # empty = the CLI's default effort
    builtin_tools: tuple[str, ...] = ("WebSearch", "WebFetch")
    turn_timeout_s: float = 120.0
    stall_timeout_s: float = 45.0


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_dir: Path
    user_name: str
    provider_order: tuple[str, ...]
    claude_plan: ClaudePlanSettings
    confirm_timeout_s: float
    notes_dir: Path
    history_turns: int
    token: str
    location: str = ""
    file_roots: tuple[Path, ...] = ()
    google_client_file: Path = Path("~/.jarvis/google_client.json").expanduser()
    google_token_file: Path = Path("~/.jarvis/google_token.json").expanduser()
    hud_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173")

    @property
    def run_dir(self) -> Path:
        return self.data_dir / "run"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"


def _path(value: str) -> Path:
    return Path(os.path.expanduser(value))


def load_settings(config_path: Path | None = None, env_path: Path | None = None) -> Settings:
    config_path = config_path or BACKEND_DIR / "config.toml"
    load_dotenv(env_path or BACKEND_DIR / ".env")
    raw = tomllib.loads(config_path.read_text()) if config_path.exists() else {}

    core = raw.get("core", {})
    user = raw.get("user", {})
    providers = raw.get("providers", {})
    claude = providers.get("claude_plan", {})
    tools = raw.get("tools", {})
    brain = raw.get("brain", {})
    google = raw.get("google", {})

    data_dir = _path(os.environ.get("JARVIS_HOME") or core.get("data_dir", "~/.jarvis"))
    defaults = ClaudePlanSettings()
    return Settings(
        host=core.get("host", "127.0.0.1"),
        port=int(core.get("port", 8765)),
        data_dir=data_dir,
        user_name=user.get("name", "") or "the user",
        provider_order=tuple(providers.get("order", ["claude_plan"])),
        claude_plan=ClaudePlanSettings(
            enabled=claude.get("enabled", defaults.enabled),
            command=claude.get("command", defaults.command),
            model=claude.get("model", defaults.model),
            effort=claude.get("effort", defaults.effort),
            builtin_tools=tuple(claude.get("builtin_tools", defaults.builtin_tools)),
            turn_timeout_s=float(claude.get("turn_timeout_s", defaults.turn_timeout_s)),
            stall_timeout_s=float(claude.get("stall_timeout_s", defaults.stall_timeout_s)),
        ),
        confirm_timeout_s=float(tools.get("confirm_timeout_s", 30)),
        notes_dir=_path(tools.get("notes_dir", str(data_dir / "notes"))),
        history_turns=int(brain.get("history_turns", 20)),
        token=os.environ.get("JARVIS_TOKEN", ""),
        hud_origins=tuple(core.get("hud_origins", Settings.hud_origins)),
        location=user.get("location", ""),
        file_roots=tuple(
            _path(p) for p in tools.get("file_roots", ["~/Documents", "~/Desktop", "~/Downloads"])
        ),
        google_client_file=_path(google.get("client_file", str(data_dir / "google_client.json"))),
        google_token_file=_path(google.get("token_file", str(data_dir / "google_token.json"))),
    )
