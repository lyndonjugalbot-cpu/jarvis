"""JARVIS core entry point.

python main.py serve   # HUD backend on 127.0.0.1 (WebSocket arrives in Phase 3)
python main.py chat    # Phase 1 terminal chat
"""

import argparse
import asyncio
import logging
from logging.handlers import RotatingFileHandler

import uvicorn
from fastapi import FastAPI

from config import Settings, load_settings

VERSION = "0.1.0"


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


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="JARVIS core", version=VERSION)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "version": VERSION}

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS core")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "chat"])
    args = parser.parse_args(argv)
    settings = load_settings()

    if args.command == "chat":
        setup_logging(settings, console=False)  # details go to ~/.jarvis/logs, the chat stays clean
        from terminal import run_chat

        try:
            asyncio.run(run_chat(settings))
        except KeyboardInterrupt:
            print()
        return

    setup_logging(settings, console=True)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_config=None)


if __name__ == "__main__":
    main()
