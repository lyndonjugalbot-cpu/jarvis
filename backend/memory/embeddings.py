"""Local text embeddings with fastembed (ONNX, CPU): private and free.

The model (BAAI/bge-small-en-v1.5, 384 dimensions, ~67 MB) downloads once into ~/.jarvis/models.
Vectors are normalized, so a dot product is the cosine similarity.
"""

import asyncio
import logging
import threading
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)


class Embedder(Protocol):
    async def documents(self, texts: list[str]) -> np.ndarray: ...

    async def query(self, text: str) -> np.ndarray: ...


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return (vectors / np.maximum(norms, 1e-12)).astype(np.float32)


class FastEmbedder:
    def __init__(self, model_name: str, cache_dir: Path) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                log.info("loading embedding model %s", self._model_name)
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                self._model = TextEmbedding(
                    model_name=self._model_name, cache_dir=str(self._cache_dir)
                )
            return self._model

    async def warm_up(self) -> None:
        await asyncio.to_thread(self._load)

    async def documents(self, texts: list[str]) -> np.ndarray:
        def run() -> np.ndarray:
            return _normalize(np.array(list(self._load().embed(texts)), dtype=np.float32))

        return await asyncio.to_thread(run)

    async def query(self, text: str) -> np.ndarray:
        def run() -> np.ndarray:
            # bge models embed queries with a retrieval instruction; fastembed adds it here.
            return _normalize(np.array(list(self._load().query_embed(text)), dtype=np.float32))[0]

        return await asyncio.to_thread(run)
