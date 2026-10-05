"""Phase 1 terminal chat. Risky tools ask for a typed y/N in place of the HUD's thumbs-up."""

import asyncio
import sys
import threading
from datetime import datetime

from brain.providers.claude_cli import ClaudeCliProvider
from brain.router import NoProviderAvailable
from config import Settings
from core import Core, start_core
from events import EventBus

TTY = sys.stdout.isatty()


def _style(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if TTY else text


def cyan(text: str) -> str:
    return _style("36", text)


def dim(text: str) -> str:
    return _style("2", text)


def yellow(text: str) -> str:
    return _style("33", text)


def _clock(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%a %H:%M")


class Lines:
    """Reads stdin on a thread so the chat prompt and confirmations can share it."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        threading.Thread(target=self._read, args=(loop,), daemon=True).start()

    def _read(self, loop: asyncio.AbstractEventLoop) -> None:
        for line in sys.stdin:
            loop.call_soon_threadsafe(self._queue.put_nowait, line.rstrip("\n"))
        loop.call_soon_threadsafe(self._queue.put_nowait, None)

    async def get(self, prompt: str) -> str | None:
        print(prompt, end="", flush=True)
        line = await self._queue.get()
        if line is not None and not sys.stdin.isatty():
            print(line)  # echo piped input so transcripts read naturally
        return line


def make_confirmer(lines: Lines):
    async def confirm(summary: str) -> bool:
        try:
            answer = await lines.get(f"\n  {yellow('?')} {summary} [y/N] ")
        except asyncio.CancelledError:
            print(dim("(no answer, so no)"))
            raise
        return (answer or "").strip().lower() in ("y", "yes")

    return confirm


def _status(core: Core) -> str:
    rows = [f"active provider: {core.router.active or 'none yet'}"]
    for name, until in core.router.status()["coolingDown"].items():
        rows.append(f"{name}: cooling down until {_clock(until)}")
    for p in core.providers:
        if isinstance(p, ClaudeCliProvider) and p.last_rate_limit:
            windows = p.last_rate_limit.get("unifiedWindows") or {}
            for window, info in windows.items():
                used = info.get("utilization")
                if used is not None:
                    rows.append(
                        f"{p.label} {window.replace('_', '-')} window: {used:.0%} used, "
                        f"resets {_clock(info.get('resetsAt', 0))}"
                    )
    return "\n".join("  " + dim(r) for r in rows)


async def run_chat(settings: Settings) -> None:
    lines = Lines()
    events = EventBus()
    events.subscribe(
        "provider.limit",
        lambda label, until, **_: print(
            f"  {yellow('!')} {label} limit reached; available again {_clock(until)}"
        ),
    )
    events.subscribe(
        "provider.active",
        lambda label, previous, **_: previous and print(f"  {yellow('>')} switching to {label}"),
    )
    events.subscribe(
        "budget.warning",
        lambda spent, cap, **_: print(
            f"  {yellow('!')} paid API: ${spent:.2f} of ${cap:.2f} used this month"
        ),
    )
    events.subscribe(
        "budget.exhausted",
        lambda spent, cap, **_: print(
            f"  {yellow('!')} paid API: monthly ${cap:.2f} used up; off until next month"
        ),
    )

    core = await start_core(settings, confirmer=make_confirmer(lines), events=events)
    try:
        print(cyan("JARVIS") + dim(" | terminal chat | /status, /quit"))
        while True:
            text = await lines.get(f"\n{cyan('you')} > ")
            if text is None or text.strip() in ("/quit", "/exit"):
                break
            if not text.strip():
                continue
            if text.strip() == "/status":
                print(_status(core))
                continue
            try:
                reply = await core.brain.ask(text)
            except NoProviderAvailable as e:
                when = f" The next one is back {_clock(e.next_reset)}." if e.next_reset else ""
                print(f"{cyan('jarvis')} > I can't answer right now: {e}.{when}")
                continue
            spend = f"${reply.cost_usd:.4f} API spend" if reply.cost_usd else "$0.00 API spend"
            meta = [reply.provider, f"{reply.duration_s:.1f}s", *reply.tools_used, spend]
            print(f"{cyan('jarvis')} > {reply.text}")
            print("  " + dim(" | ".join(meta)))
    finally:
        await core.close()
