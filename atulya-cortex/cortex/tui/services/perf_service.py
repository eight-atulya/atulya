from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass
class TurnMetric:
    elapsed_ms: int
    ok: bool


class PerfService:
    def __init__(self, max_items: int = 200) -> None:
        self._items: deque[TurnMetric] = deque(maxlen=max_items)
        self._started_at: float | None = None

    def start(self) -> None:
        self._started_at = time.perf_counter()

    def stop(self, *, ok: bool) -> int:
        if self._started_at is None:
            elapsed_ms = 0
        else:
            elapsed_ms = int((time.perf_counter() - self._started_at) * 1000)
        self._items.append(TurnMetric(elapsed_ms=elapsed_ms, ok=ok))
        self._started_at = None
        return elapsed_ms

    def snapshot(self) -> dict[str, int]:
        total = len(self._items)
        if total == 0:
            return {"turns": 0, "avg_ms": 0, "errors": 0}
        avg = sum(i.elapsed_ms for i in self._items) // total
        errors = sum(1 for i in self._items if not i.ok)
        return {"turns": total, "avg_ms": avg, "errors": errors}
