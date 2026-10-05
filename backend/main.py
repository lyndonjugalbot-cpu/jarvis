"""JARVIS core entry point.

python main.py serve          # core for the HUD: WebSocket /ws on 127.0.0.1
python main.py chat           # terminal chat
python main.py google-login   # connect Calendar and Gmail (docs/google-setup.md)
python main.py clear-logs     # delete the log files
"""

import argparse
import asyncio
import hmac
import json
import logging
import os
import secrets
import sys
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from config import BACKEND_DIR, Settings, load_settings
from core import start_core
from events import EventBus
from hud_bridge import HudAssistant, HudBridge

VERSION = "0.1.0"
AUTH_TIMEOUT_S = 2.0
MAX_TEXT = 4000
HUD_DIST = BACKEND_DIR.parent / "frontend" / "dist"

# WebSocket close codes
UNAUTHORIZED = 4401
FORBIDDEN_ORIGIN = 4403

log = logging.getLogger("jarvis")


def setup_logging(settings: Settings, *, console: bool) -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(settings.log_dir / "jarvis.log", maxBytes=1_000_000, backupCount=3)
    ]
    if console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def create_app(
    settings: Settings,
    *,
    core_factory=start_core,
    auth_timeout_s: float = AUTH_TIMEOUT_S,
    voice_enabled: bool = True,
) -> FastAPI:
    bridge = HudBridge()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not settings.token:
            log.error("JARVIS_TOKEN is missing from backend/.env; run scripts/setup.sh")
        events = EventBus()
        core = await core_factory(settings, confirmer=bridge.confirm, events=events, hud=bridge)
        assistant = HudAssistant(core, bridge)

        async def provider_changed(**_):
            await bridge.broadcast("provider", assistant.provider_status())

        async def google_lost(reason: str = "", **_):
            await bridge.broadcast(
                "auth_needed",
                {
                    "service": "google",
                    "message": "JARVIS lost access to Google. Reconnect to use Calendar and Gmail.",
                },
            )

        async def budget_notice(spent: float, cap: float, **_):
            used_up = spent >= cap
            message = (
                f"The paid Claude API has used its ${cap:.2f} for this month; off until next month."
                if used_up
                else f"The paid Claude API has used ${spent:.2f} of its ${cap:.2f} this month."
            )
            await bridge.broadcast("error", {"message": message})
            await bridge.broadcast("provider", assistant.provider_status())

        events.subscribe("provider.active", provider_changed)
        events.subscribe("provider.limit", provider_changed)
        events.subscribe("budget.warning", budget_notice)
        events.subscribe("budget.exhausted", budget_notice)
        events.subscribe("google.lost", google_lost)
        app.state.assistant = assistant
        app.state.core = core
        app.state.voice = None
        if settings.voice.enabled and voice_enabled:
            from voice.service import VoiceService

            app.state.voice = VoiceService(
                settings.voice, settings.data_dir / "models", assistant, bridge
            )
            app.state.voice.start()
        try:
            yield
        finally:
            if app.state.voice:
                await app.state.voice.stop()
            await core.close()

    app = FastAPI(title="JARVIS core", version=VERSION, lifespan=lifespan)
    # Only the HUD's own pages may connect, so other websites open in the browser can't.
    allowed_origins = {*settings.hud_origins, f"http://{settings.host}:{settings.port}"}

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "version": VERSION}

    async def authenticate(ws: WebSocket) -> bool:
        """The token comes as the first message: browsers can't set WebSocket headers."""
        try:
            first = await asyncio.wait_for(ws.receive_json(), auth_timeout_s)
        except (TimeoutError, ValueError, WebSocketDisconnect):
            return False
        token = (
            str((first.get("payload") or {}).get("token", "")) if isinstance(first, dict) else ""
        )
        return (
            isinstance(first, dict)
            and first.get("type") == "auth"
            and bool(settings.token)
            and hmac.compare_digest(token.encode(), settings.token.encode())
        )

    @app.websocket("/ws")
    async def hud_socket(ws: WebSocket) -> None:
        origin = ws.headers.get("origin", "")
        if origin not in allowed_origins:
            log.warning("refused a WebSocket from origin %r", origin)
            await ws.close(code=FORBIDDEN_ORIGIN)
            return
        await ws.accept()
        if not await authenticate(ws):
            await ws.close(code=UNAUTHORIZED)
            return

        assistant: HudAssistant = app.state.assistant
        bridge.add(ws)
        try:
            await bridge.send(ws, "auth_ok", {"session": secrets.token_hex(4)})
            await bridge.send(ws, "provider", assistant.provider_status())
            await bridge.send(ws, "state", {"state": "idle"})
            voice = app.state.voice
            await bridge.send(ws, "mic", {"state": voice.state if voice else "off", "message": ""})
            while True:
                try:
                    message = await ws.receive_json()
                except json.JSONDecodeError:
                    await bridge.send(ws, "error", {"message": "Messages must be JSON."})
                    continue
                await handle_message(ws, message, assistant)
        except WebSocketDisconnect:
            pass
        finally:
            bridge.remove(ws)

    async def handle_message(ws: WebSocket, message: dict, assistant: HudAssistant) -> None:
        kind = message.get("type") if isinstance(message, dict) else None
        payload = (message.get("payload") or {}) if isinstance(message, dict) else {}
        if kind == "user_text":
            bridge.spawn(assistant.handle_text(str(payload.get("text", ""))[:MAX_TEXT]))
        elif kind == "confirm":
            bridge.resolve(str(payload.get("actionId", "")), payload.get("approved") is True)
        elif kind == "gesture_event":
            log.info("gesture %s on panel %s", payload.get("gesture"), payload.get("panelId"))
        elif kind == "mic":
            if app.state.voice:
                await app.state.voice.set_enabled(payload.get("on") is True)
        elif kind == "connect_google":
            bridge.spawn(connect_google(app.state.core.google))
        else:
            await bridge.send(ws, "error", {"message": f"Unknown message type: {kind!r}"})

    async def connect_google(google) -> None:
        """Run Google's browser sign-in on this computer and tell the HUDs how it went."""
        try:
            await asyncio.to_thread(google.login)
        except Exception as e:  # not set up, cancelled, or timed out
            log.warning("Google sign-in failed: %s", e)
            await bridge.broadcast(
                "auth_done",
                {"service": "google", "ok": False, "message": str(e) or "Sign-in didn't finish."},
            )
            return
        await bridge.broadcast(
            "auth_done", {"service": "google", "ok": True, "message": "Connected to Google."}
        )

    if HUD_DIST.is_dir():  # a built HUD (npm run build) is served by the core itself
        app.mount("/", StaticFiles(directory=HUD_DIST, html=True), name="hud")

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS core")
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=["serve", "chat", "google-login", "clear-logs"],
    )
    args = parser.parse_args(argv)
    settings = load_settings()

    if args.command == "google-login":
        from auth.google import GoogleAuth, GoogleNotConnected

        google = GoogleAuth(settings.google_client_file, settings.google_token_file)
        try:
            print("Opening Google's sign-in page in your browser...")
            google.login()
        except GoogleNotConnected as e:
            raise SystemExit(str(e)) from None
        print(f"Connected. The sign-in is saved in {google.token_file}.")
        return

    if args.command == "clear-logs":
        removed = [p for p in settings.log_dir.glob("jarvis.log*") if p.is_file()]
        for path in removed:
            path.unlink()
        print(f"Removed {len(removed)} log file(s) from {settings.log_dir}.")
        return

    if args.command == "chat":
        setup_logging(settings, console=False)  # details go to ~/.jarvis/logs, the chat stays clean
        from terminal import run_chat

        try:
            asyncio.run(run_chat(settings))
        except KeyboardInterrupt:
            print()
        _exit_now()

    setup_logging(settings, console=True)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_config=None)
    _exit_now()


def _exit_now() -> None:
    """Everything is closed by now. Skip interpreter teardown: the native speech and ONNX
    libraries can abort in their exit-time destructors, which macOS reports as a crash."""
    logging.shutdown()
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
