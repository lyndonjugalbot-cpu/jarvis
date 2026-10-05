"""Paid API spend, tracked per calendar month in SQLite against a hard cap (spec 3.3).

`fallback` decides whether the paid tier may run at all: "auto" (whenever everything else is
unavailable), "ask" (approval once a day) or "off". Events: budget.warning once at 80% of the
cap, budget.exhausted once at 100%.
"""

import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from events import EventBus

WARN_AT = 0.8


class Budget:
    def __init__(
        self,
        db_path: Path,
        cap_usd: float,
        fallback: str = "auto",
        events: EventBus | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.cap_usd = cap_usd
        self.fallback = fallback
        self._events = events or EventBus()
        self._now = now
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS paid_spend (
                month TEXT PRIMARY KEY,
                usd REAL NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                calls INTEGER NOT NULL DEFAULT 0,
                warned INTEGER NOT NULL DEFAULT 0,
                exhausted INTEGER NOT NULL DEFAULT 0
            )"""
        )
        self._db.commit()

    def month(self) -> str:
        return self._now().strftime("%Y-%m")

    def next_month_start(self) -> float:
        now = self._now()
        first = datetime(now.year + (now.month == 12), now.month % 12 + 1, 1)
        return first.timestamp()

    def spent(self) -> float:
        row = self._db.execute(
            "SELECT usd FROM paid_spend WHERE month = ?", (self.month(),)
        ).fetchone()
        return row[0] if row else 0.0

    def remaining(self) -> float:
        return max(0.0, self.cap_usd - self.spent())

    @property
    def enabled(self) -> bool:
        return self.fallback != "off"

    def allows(self, estimate_usd: float) -> bool:
        """Whether a call that could cost up to `estimate_usd` stays within the cap."""
        return self.enabled and self.spent() + estimate_usd <= self.cap_usd

    async def record(self, usd: float, input_tokens: int = 0, output_tokens: int = 0) -> None:
        month = self.month()
        self._db.execute(
            """INSERT INTO paid_spend (month, usd, input_tokens, output_tokens, calls)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT(month) DO UPDATE SET usd = usd + excluded.usd,
                 input_tokens = input_tokens + excluded.input_tokens,
                 output_tokens = output_tokens + excluded.output_tokens,
                 calls = calls + 1""",
            (month, usd, input_tokens, output_tokens),
        )
        self._db.commit()
        spent = self.spent()
        warned, exhausted = self._db.execute(
            "SELECT warned, exhausted FROM paid_spend WHERE month = ?", (month,)
        ).fetchone()
        if spent >= self.cap_usd * WARN_AT and not warned:
            self._db.execute("UPDATE paid_spend SET warned = 1 WHERE month = ?", (month,))
            self._db.commit()
            await self._events.publish("budget.warning", spent=spent, cap=self.cap_usd)
        if spent >= self.cap_usd and not exhausted:
            self._db.execute("UPDATE paid_spend SET exhausted = 1 WHERE month = ?", (month,))
            self._db.commit()
            await self._events.publish("budget.exhausted", spent=spent, cap=self.cap_usd)

    def summary(self) -> dict:
        return {
            "month": self.month(),
            "spent_usd": round(self.spent(), 4),
            "cap_usd": self.cap_usd,
            "fallback": self.fallback,
        }

    def close(self) -> None:
        self._db.close()
