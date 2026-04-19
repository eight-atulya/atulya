"""heartbeat.py — the async cron pulse.

`Heartbeat` schedules background callbacks on a fixed period. Every cron job
in the cortex (dream consolidation, working-memory eviction, reflex
expiration sweep) hangs off one Heartbeat instance.

Naming voice: `Heartbeat.start` / `pulse` / `stop`. Each pulse fires every
registered callback in parallel; long callbacks do not block the next pulse
(the next pulse runs while the slow one finishes).
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

PulseCallback = Callable[[], Awaitable[None]]


class Heartbeat:
    """Fixed-period async cron."""

    def __init__(self, *, interval_s: float = 60.0) -> None:
        if interval_s <= 0:
            raise ValueError("interval_s must be > 0")
        self._interval_s = float(interval_s)
        self._callbacks: dict[str, PulseCallback] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._pulse_count = 0
        self._last_pulse_at: float | None = None

    @property
    def interval_s(self) -> float:
        return self._interval_s

    @property
    def pulse_count(self) -> int:
        return self._pulse_count

    @property
    def last_pulse_at(self) -> float | None:
        return self._last_pulse_at

    def register(self, name: str, callback: PulseCallback) -> None:
        self._callbacks[name] = callback

    def unregister(self, name: str) -> None:
        self._callbacks.pop(name, None)

    def jobs(self) -> list[str]:
        return sorted(self._callbacks.keys())

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="cortex.heartbeat")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=self._interval_s + 1.0)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None

    async def pulse(self) -> None:
        """Fire one pulse manually. Useful for tests and explicit nudges."""

        self._pulse_count += 1
        self._last_pulse_at = time.monotonic()
        if not self._callbacks:
            return
        coros = [self._safe_call(name, cb) for name, cb in self._callbacks.items()]
        await asyncio.gather(*coros)

    async def _safe_call(self, name: str, callback: PulseCallback) -> None:
        try:
            await callback()
        except Exception:
            return

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_s)
                return
            except asyncio.TimeoutError:
                await self.pulse()


__all__ = ["Heartbeat", "PulseCallback"]
