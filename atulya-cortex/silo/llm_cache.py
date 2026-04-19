"""llm_cache.py — completion cache.

Caches `Utterance`s keyed by `(provider, model, messages, temperature, max_tokens)`.
The cache is content-addressed: a deterministic blake2b hash of the inputs
is the disk key. We deliberately do *not* cache when temperature > 0.7
unless the caller passes `force=True` (high-temp answers should vary).

Backed by `diskcache.Cache`, so the same on-disk store can be shared across
processes (TUI, telegram poller, dream loop). TTL is optional.

Naming voice: `LLMCache.remember` / `recall` / `forget`. The cortex's
existing recall verbs are reused: a silo "remembers" what the LLM said.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from cortex.language import Utterance


def _stringify(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, dict):
        return {str(k): _stringify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_stringify(v) for v in obj]
    return repr(obj)


def _key(
    *,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int | None,
    extra: dict[str, Any] | None,
) -> str:
    payload = {
        "provider": provider,
        "model": model,
        "messages": _stringify(messages),
        "temperature": round(float(temperature), 3),
        "max_tokens": max_tokens,
        "extra": _stringify(extra) if extra else None,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.blake2b(blob, digest_size=20).hexdigest()


class LLMCache:
    """diskcache-backed completion cache."""

    DEFAULT_HOT_TEMPERATURE = 0.7

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        size_limit_bytes: int = 1_000_000_000,
        cache: Any | None = None,
    ) -> None:
        if cache is not None:
            self._cache = cache
        else:
            from diskcache import Cache

            Path(path).mkdir(parents=True, exist_ok=True)
            self._cache = Cache(str(path), size_limit=size_limit_bytes)

    def close(self) -> None:
        try:
            self._cache.close()
        except Exception:
            pass

    def __len__(self) -> int:
        return len(self._cache)

    def recall(
        self,
        *,
        provider: str,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Utterance | None:
        key = _key(
            provider=provider,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra=extra,
        )
        raw = self._cache.get(key)
        if raw is None:
            return None
        try:
            return Utterance(**raw) if isinstance(raw, dict) else raw
        except TypeError:
            return None

    def remember(
        self,
        utterance: Utterance,
        *,
        provider: str,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
        ttl: float | None = None,
        force: bool = False,
    ) -> bool:
        if temperature > self.DEFAULT_HOT_TEMPERATURE and not force:
            return False
        key = _key(
            provider=provider,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra=extra,
        )
        self._cache.set(key, asdict(utterance), expire=ttl)
        return True

    def forget(
        self,
        *,
        provider: str,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        key = _key(
            provider=provider,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra=extra,
        )
        self._cache.delete(key)


__all__ = ["LLMCache"]
