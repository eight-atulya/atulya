"""entanglement.py — background recall prefetch.

When a `Stimulus` arrives we usually need recollections for it. Recall is
the slow step (vector search > 1k vectors easily costs 50-200 ms). We can
hide that latency by *prefetching*: kick off the recall coroutines the
moment a Stimulus is observed, even before the cortex has decided whether
to consult them. By the time the cortex's main loop calls
`get(stim)`, the future is usually already done.

Cancellation is automatic: if no one consumes a prefetch within
`max_age_s`, the entanglement is forgotten and the underlying task is
cancelled.

Naming voice: `Entanglement.entangle` to start a prefetch, `Entanglement.get`
to await the (probably already done) result.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from cortex.bus import Recollection, Stimulus

RecallCallable = Callable[[str, str, str | None], Awaitable[list[Recollection]]]


@dataclass
class _Pending:
    task: asyncio.Task[list[Recollection]]
    created_at: float


class Entanglement:
    """Background recall prefetch."""

    def __init__(
        self,
        recall: RecallCallable,
        *,
        kinds: tuple[str, ...] = ("episodic", "semantic"),
        top_k: int = 4,
        max_age_s: float = 30.0,
    ) -> None:
        self._recall = recall
        self._kinds = tuple(kinds)
        self._top_k = max(1, int(top_k))
        self._max_age_s = float(max_age_s)
        self._pending: dict[str, _Pending] = {}

    def _key(self, stimulus: Stimulus, kind: str) -> str:
        return f"{kind}::{stimulus.channel}::{stimulus.text or ''}"

    def entangle(self, stimulus: Stimulus) -> None:
        """Kick off background recall for every kind."""

        if not stimulus.text:
            return
        self.gc()
        for kind in self._kinds:
            key = self._key(stimulus, kind)
            if key in self._pending:
                continue
            task = asyncio.create_task(self._recall(stimulus.text, kind, None))
            self._pending[key] = _Pending(task=task, created_at=time.monotonic())

    async def get(self, stimulus: Stimulus, kind: str) -> list[Recollection]:
        """Await the prefetched result; fall back to a fresh recall if absent."""

        if not stimulus.text:
            return []
        key = self._key(stimulus, kind)
        pending = self._pending.pop(key, None)
        if pending is not None:
            try:
                items = await pending.task
            except Exception:
                items = []
            return items[: self._top_k]
        try:
            items = await self._recall(stimulus.text, kind, None)
        except Exception:
            items = []
        return items[: self._top_k]

    def gc(self) -> int:
        """Cancel and forget any prefetches older than `max_age_s`. Returns count."""

        now = time.monotonic()
        cutoff = now - self._max_age_s
        stale = [k for k, p in self._pending.items() if p.created_at < cutoff]
        for k in stale:
            p = self._pending.pop(k)
            if not p.task.done():
                p.task.cancel()
        return len(stale)

    async def aclose(self) -> None:
        for p in list(self._pending.values()):
            if not p.task.done():
                p.task.cancel()
        for p in self._pending.values():
            try:
                await p.task
            except (asyncio.CancelledError, Exception):
                pass
        self._pending.clear()

    @property
    def pending_count(self) -> int:
        return len(self._pending)


__all__ = ["Entanglement", "RecallCallable"]
