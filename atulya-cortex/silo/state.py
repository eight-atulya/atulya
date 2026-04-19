"""state.py — durable per-bank state.

A simple JSON-backed key/value store for cortex state that needs to survive
process restarts: dream tick counters, last consolidation timestamp,
working-memory snapshot, channel activity counts. Atomic writes via
write-then-rename.

Naming voice: `StateStore.remember` / `recall` / `forget`.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class StateStore:
    """Atomic JSON KV store."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._state: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return {}
        if not text.strip():
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return dict(data) if isinstance(data, dict) else {}

    def _save(self) -> None:
        d = self._path.parent
        d.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(d), prefix=".state-", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._state, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def keys(self) -> list[str]:
        return sorted(self._state.keys())

    def recall(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)

    def remember(self, key: str, value: Any) -> None:
        self._state[key] = value
        self._save()

    def forget(self, key: str) -> None:
        if key in self._state:
            self._state.pop(key)
            self._save()

    def update(self, mapping: dict[str, Any]) -> None:
        self._state.update(mapping)
        self._save()

    def snapshot(self) -> dict[str, Any]:
        return dict(self._state)


__all__ = ["StateStore"]
