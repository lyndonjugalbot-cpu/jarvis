"""Long-term memory in SQLite (spec 5.4).

- facts: key -> value (e.g. preferred_name = Lyndon). All of them go with every request.
- messages: every exchange, so a restart picks up where the conversation left off and older
  turns can be summarized.
- memories: embedded text for recall by meaning: facts, exchanges, session summaries, notes.
  The top matches from earlier sessions go with each request.

Search is a numpy dot product over normalized vectors held in memory, which is instant at
personal scale (thousands of items).
"""

import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from memory.embeddings import Embedder

log = logging.getLogger(__name__)

SNIPPET_CHARS = 300


@dataclass(frozen=True)
class Hit:
    kind: str
    text: str
    created_at: float
    score: float

    def describe(self) -> str:
        when = datetime.fromtimestamp(self.created_at).strftime("%d %b %Y")
        label = {"exchange": "conversation", "summary": "conversation summary"}.get(
            self.kind, self.kind
        )
        text = (
            self.text if len(self.text) <= SNIPPET_CHARS else self.text[: SNIPPET_CHARS - 1] + "…"
        )
        return f"[{label}, {when}] {text}"


@dataclass(frozen=True)
class Message:
    id: int
    role: str
    text: str
    created_at: float


def fact_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_") or "fact"


class MemoryStore:
    def __init__(self, db_path: Path, embedder: Embedder, *, now=time.time) -> None:
        self._embedder = embedder
        self._now = now
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS facts (
                key TEXT PRIMARY KEY, value TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'user', updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, session TEXT NOT NULL, role TEXT NOT NULL,
                text TEXT NOT NULL, created_at REAL NOT NULL,
                summarized INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY, kind TEXT NOT NULL, ref TEXT NOT NULL,
                session TEXT, text TEXT NOT NULL, created_at REAL NOT NULL,
                embedding BLOB NOT NULL);
            CREATE INDEX IF NOT EXISTS memories_ref ON memories (kind, ref);
            """
        )
        self._db.commit()
        self._load_vectors()

    # ------------------------------------------------------------ vectors
    def _load_vectors(self) -> None:
        rows = self._db.execute(
            "SELECT id, kind, session, text, created_at, embedding FROM memories"
        ).fetchall()
        self._rows = [r[:5] for r in rows]
        self._matrix = (
            np.vstack([np.frombuffer(r[5], dtype=np.float32) for r in rows])
            if rows
            else np.zeros((0, 0), dtype=np.float32)
        )

    async def _add_memories(self, items: list[tuple[str, str, str | None, str]]) -> None:
        """items: (kind, ref, session, text)"""
        if not items:
            return
        vectors = await self._embedder.documents([text for *_, text in items])
        now = self._now()
        for (kind, ref, session, text), vector in zip(items, vectors, strict=True):
            self._db.execute(
                "INSERT INTO memories (kind, ref, session, text, created_at, embedding)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (kind, ref, session, text, now, vector.astype(np.float32).tobytes()),
            )
        self._db.commit()
        self._load_vectors()

    def _drop_memories(self, kind: str, ref: str) -> None:
        self._db.execute("DELETE FROM memories WHERE kind = ? AND ref = ?", (kind, ref))

    # ------------------------------------------------------------ facts
    async def remember(self, key: str, value: str, source: str = "user") -> str:
        key = fact_key(key)
        self._db.execute(
            """INSERT INTO facts (key, value, source, updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value, source = excluded.source,
               updated_at = excluded.updated_at""",
            (key, value.strip(), source, self._now()),
        )
        self._drop_memories("fact", key)
        await self._add_memories([("fact", key, None, f"{key.replace('_', ' ')}: {value.strip()}")])
        return key

    def facts(self) -> list[tuple[str, str]]:
        return self._db.execute("SELECT key, value FROM facts ORDER BY key").fetchall()

    # ------------------------------------------------------------ conversation
    async def add_exchange(self, session: str, user_text: str, reply_text: str) -> None:
        now = self._now()
        cur = self._db.execute(
            "INSERT INTO messages (session, role, text, created_at) VALUES (?, 'user', ?, ?)",
            (session, user_text, now),
        )
        self._db.execute(
            "INSERT INTO messages (session, role, text, created_at) VALUES (?, 'jarvis', ?, ?)",
            (session, reply_text, now),
        )
        self._db.commit()
        await self._add_memories(
            [("exchange", str(cur.lastrowid), session, f"User: {user_text}\nJARVIS: {reply_text}")]
        )

    def recent_turns(self, limit: int, max_age_s: float) -> list[tuple[str, str]]:
        """The latest turns, oldest first, if the conversation was recent enough to continue."""
        rows = self._db.execute(
            "SELECT role, text, created_at FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        if not rows or self._now() - rows[0][2] > max_age_s:
            return []
        return [(role, text) for role, text, _ in reversed(rows)]

    def unsummarized(self, session: str) -> list[Message]:
        rows = self._db.execute(
            "SELECT id, role, text, created_at FROM messages"
            " WHERE session = ? AND summarized = 0 ORDER BY id",
            (session,),
        ).fetchall()
        return [Message(*r) for r in rows]

    async def add_summary(self, session: str, text: str, message_ids: list[int]) -> None:
        self._db.executemany(
            "UPDATE messages SET summarized = 1 WHERE id = ?", [(i,) for i in message_ids]
        )
        self._db.commit()
        ref = f"{session}:{min(message_ids)}-{max(message_ids)}"
        await self._add_memories([("summary", ref, session, text)])

    # ------------------------------------------------------------ notes
    async def index_note(self, title: str, text: str) -> None:
        ref = fact_key(title)
        self._drop_memories("note", ref)
        await self._add_memories([("note", ref, None, f"Note '{title}': {text.strip()[:1500]}")])

    # ------------------------------------------------------------ recall
    async def search(
        self, query: str, k: int = 5, min_score: float = 0.0, *, exclude_session: str | None = None,
        kinds: tuple[str, ...] = ("fact", "exchange", "summary", "note"),
    ) -> list[Hit]:  # fmt: skip
        if not self._rows:
            return []
        scores = self._matrix @ await self._embedder.query(query)
        hits = []
        for i in np.argsort(-scores):
            _, kind, session, text, created = self._rows[i]
            if scores[i] < min_score:
                break
            if kind not in kinds or (
                exclude_session and session == exclude_session and kind == "exchange"
            ):
                continue  # this session's exchanges are already in the history
            hits.append(Hit(kind, text, created, float(scores[i])))
            if len(hits) == k:
                break
        return hits

    async def context_for(self, text: str, *, session: str, k: int, min_score: float) -> list[str]:
        """What goes with a request: every fact, plus the best matches from earlier sessions."""
        lines = [f"{key.replace('_', ' ')}: {value}" for key, value in self.facts()]
        hits = await self.search(
            text, k, min_score, exclude_session=session, kinds=("exchange", "summary", "note")
        )
        return lines + [hit.describe() for hit in hits]

    # ------------------------------------------------------------ forgetting
    def _matching(self, topic: str) -> tuple[list[str], list[int], list[int]]:
        like = f"%{topic.strip().lower()}%"
        key = fact_key(topic)
        facts = [
            r[0]
            for r in self._db.execute(
                "SELECT key FROM facts WHERE key = ? OR lower(key) LIKE ? OR lower(value) LIKE ?",
                (key, like, like),
            )
        ]
        # whole exchanges, identified by their user message id, when either half mentions the topic
        exchanges = sorted(
            {
                r[0] if r[1] == "user" else r[0] - 1
                for r in self._db.execute(
                    "SELECT id, role FROM messages WHERE lower(text) LIKE ?", (like,)
                )
            }
        )
        summaries = [
            r[0]
            for r in self._db.execute(
                "SELECT id FROM memories WHERE kind = 'summary' AND lower(text) LIKE ?", (like,)
            )
        ]
        return facts, exchanges, summaries

    def forget_preview(self, topic: str) -> dict:
        facts, exchanges, summaries = self._matching(topic)
        return {"facts": len(facts), "exchanges": len(exchanges), "summaries": len(summaries)}

    def forget(self, topic: str) -> dict:
        """Delete facts, conversation messages and summaries about a topic. Notes stay."""
        facts, exchanges, summaries = self._matching(topic)
        for key in facts:
            self._db.execute("DELETE FROM facts WHERE key = ?", (key,))
            self._drop_memories("fact", key)
        for user_id in exchanges:
            self._db.execute("DELETE FROM messages WHERE id IN (?, ?)", (user_id, user_id + 1))
            self._drop_memories("exchange", str(user_id))
        for memory_id in summaries:
            self._db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._db.commit()
        self._load_vectors()
        return {"facts": len(facts), "exchanges": len(exchanges), "summaries": len(summaries)}

    def close(self) -> None:
        self._db.close()
