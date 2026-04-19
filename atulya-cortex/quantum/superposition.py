"""superposition.py — speculative tool execution (idempotent only).

A speculation is a piece of work the cortex *might* want, executed before
it has decided. If the cortex commits, we return the already-computed
result instantly; if it rolls back, we throw the result away.

Crucial safety invariant in v1: **only side-effect-free work may be
speculated**. Concretely, the speculation API requires the caller to
declare a tool as `idempotent=True` *and* a name in the
`SAFE_IDEMPOTENT_TOOLS` allowlist. Any attempt to speculate a
non-idempotent tool raises `SpeculationDenied`.

The allowlist starts with the read-only tools shipped by the `Hand`:
`read_file`, `web_fetch`. Adding to the list is intentionally a code
change; that keeps the safety bar high.

Naming voice: `Superposition.speculate` / `commit` / `rollback`. Speculate
returns a `Speculation` handle; commit/rollback consume it exactly once.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

SAFE_IDEMPOTENT_TOOLS: frozenset[str] = frozenset({"read_file", "web_fetch"})


class SpeculationDenied(RuntimeError):
    """Raised when a non-idempotent tool is speculated."""


@dataclass
class Speculation:
    """Opaque receipt for one speculation."""

    id: str
    tool: str
    started_at: float
    task: asyncio.Task[Any]
    settled: bool = False
    rolled_back: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return self.task.done()


class Superposition:
    """Speculative-execution registry. Only idempotent tools are allowed."""

    def __init__(self, *, allowed_tools: frozenset[str] | None = None) -> None:
        self._allowed = allowed_tools or SAFE_IDEMPOTENT_TOOLS
        self._open: dict[str, Speculation] = {}

    @property
    def allowed_tools(self) -> frozenset[str]:
        return self._allowed

    @property
    def in_flight(self) -> int:
        return sum(1 for s in self._open.values() if not s.settled)

    def speculate(
        self,
        *,
        tool: str,
        idempotent: bool,
        work: Callable[[], Awaitable[Any]],
    ) -> Speculation:
        if not idempotent:
            raise SpeculationDenied(f"speculate requires idempotent=True (tool={tool!r})")
        if tool not in self._allowed:
            raise SpeculationDenied(f"tool {tool!r} not in safe-idempotent allowlist {sorted(self._allowed)}")
        spec_id = uuid.uuid4().hex
        task = asyncio.create_task(work())
        spec = Speculation(id=spec_id, tool=tool, started_at=time.monotonic(), task=task)
        self._open[spec_id] = spec
        return spec

    async def commit(self, spec: Speculation) -> Any:
        if spec.settled:
            raise RuntimeError(f"speculation {spec.id} already settled")
        try:
            result = await spec.task
        except Exception:
            spec.settled = True
            self._open.pop(spec.id, None)
            raise
        spec.settled = True
        self._open.pop(spec.id, None)
        return result

    async def rollback(self, spec: Speculation) -> None:
        if spec.settled:
            return
        if not spec.task.done():
            spec.task.cancel()
        try:
            await spec.task
        except (asyncio.CancelledError, Exception):
            pass
        spec.settled = True
        spec.rolled_back = True
        self._open.pop(spec.id, None)

    async def rollback_all(self) -> int:
        n = 0
        for spec in list(self._open.values()):
            if spec.settled:
                continue
            await self.rollback(spec)
            n += 1
        return n


__all__ = ["SAFE_IDEMPOTENT_TOOLS", "Speculation", "SpeculationDenied", "Superposition"]
