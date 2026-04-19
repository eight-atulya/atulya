"""embedding_cache.py — embedding cache.

Caches embeddings keyed by `(model, text)`. The same `diskcache.Cache`
abstraction as `llm_cache.py`. Embeddings are deterministic for a given
model + text so this cache is always safe to read.

Naming voice: `EmbeddingCache.remember` / `recall` / `forget`.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Sequence


def _key(model: str, text: str) -> str:
    payload = f"{model}\x00{text}".encode("utf-8")
    return hashlib.blake2b(payload, digest_size=20).hexdigest()


class EmbeddingCache:
    """diskcache-backed embedding cache."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        size_limit_bytes: int = 500_000_000,
        cache: Any | None = None,
    ) -> None:
        if cache is not None:
            self._cache = cache
        else:
            from diskcache import Cache

            Path(path).mkdir(parents=True, exist_ok=True)
            self._cache = Cache(str(path), size_limit=size_limit_bytes)

    def __len__(self) -> int:
        return len(self._cache)

    def close(self) -> None:
        try:
            self._cache.close()
        except Exception:
            pass

    def recall(self, *, model: str, text: str) -> list[float] | None:
        raw = self._cache.get(_key(model, text))
        if raw is None:
            return None
        return list(raw)

    def remember(
        self,
        embedding: Sequence[float],
        *,
        model: str,
        text: str,
        ttl: float | None = None,
    ) -> None:
        self._cache.set(_key(model, text), list(embedding), expire=ttl)

    def forget(self, *, model: str, text: str) -> None:
        self._cache.delete(_key(model, text))


__all__ = ["EmbeddingCache"]
