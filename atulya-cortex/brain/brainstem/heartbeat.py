"""heartbeat.py — the rhythmic pulse that sustains all background work.

Brain analog: the heartbeat. Every background job in the brain fires on
heartbeat pulses — medulla health checks, hippocampus memory flush,
consolidation sweeps, hypothalamus resource monitoring.

This is multi-rate: each callback declares a timescale and min_interval.
One heartbeat loop, multiple frequencies. Fast callbacks fire every pulse.
Slow callbacks fire every 5 minutes. Glacial callbacks fire every hour.
No separate threads, no complex scheduling.

Guarantees:
  - Parallel execution per pulse (slow callback never blocks fast one)
  - Fault isolation per callback (exception logged, never crashes heartbeat)
  - Manual pulse() for testing
  - Multi-rate via per-callback interval check

Migrated from POC brainstem/heartbeat.py with multi-rate addition
per BRAIN.yaml flaw_5 correction.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal

log = logging.getLogger("brain.brainstem.heartbeat")

PulseCallback = Callable[[], Awaitable[None]]

# ---------------------------------------------------------------------------
# Timescales — how often different brain regions need to fire
# ---------------------------------------------------------------------------

Timescale = Literal["fast", "medium", "slow", "glacial", "geological"]

TIMESCALE_DEFAULTS: dict[str, float] = {
    "fast": 0.0,          # every pulse
    "medium": 60.0,       # every minute
    "slow": 300.0,        # every 5 minutes
    "glacial": 3600.0,    # every hour
    "geological": 86400.0,  # every day
}


@dataclass
class TimedCallback:
    """A callback tagged with its firing frequency."""
    name: str
    callback: PulseCallback
    timescale: str
    min_interval_s: float
    last_fired_at: float = 0.0

    def is_due(self, now: float) -> bool:
        """Has enough time passed since last firing?"""
        return (now - self.last_fired_at) >= self.min_interval_s


# ---------------------------------------------------------------------------
# Heartbeat — multi-rate async cron
# ---------------------------------------------------------------------------

class Heartbeat:
    """Fixed-period async cron with multi-rate callback support.

    Usage:
        hb = Heartbeat(interval_s=60.0)

        # Fast callback — fires every pulse
        hb.register("medulla", medulla.check)

        # Slow callback — fires every 5 minutes
        hb.register("hypothalamus", hypo.monitor, timescale="slow")

        # Custom interval
        hb.register("consolidation", consolidate, min_interval_s=1800.0)

        await hb.start()
        # ... brain runs ...
        await hb.stop()
    """

    def __init__(self, *, interval_s: float = 60.0) -> None:
        if interval_s <= 0:
            raise ValueError("interval_s must be > 0")
        self._interval_s = float(interval_s)
        self._callbacks: dict[str, TimedCallback] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._pulse_count: int = 0
        self._last_pulse_at: float | None = None

    # -- properties --

    @property
    def interval_s(self) -> float:
        return self._interval_s

    @property
    def pulse_count(self) -> int:
        return self._pulse_count

    @property
    def last_pulse_at(self) -> float | None:
        return self._last_pulse_at

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # -- registration --

    def register(
        self,
        name: str,
        callback: PulseCallback,
        *,
        timescale: str = "fast",
        min_interval_s: float | None = None,
    ) -> None:
        """Register a callback with optional timescale or explicit interval.

        If min_interval_s is given, it overrides the timescale default.
        If neither is given, defaults to timescale="fast" (every pulse).
        """
        if min_interval_s is None:
            min_interval_s = TIMESCALE_DEFAULTS.get(timescale, 0.0)
        self._callbacks[name] = TimedCallback(
            name=name,
            callback=callback,
            timescale=timescale,
            min_interval_s=min_interval_s,
            last_fired_at=0.0,
        )

    def unregister(self, name: str) -> None:
        self._callbacks.pop(name, None)

    def jobs(self) -> list[str]:
        """List registered callback names, sorted."""
        return sorted(self._callbacks.keys())

    def job_info(self) -> list[dict[str, object]]:
        """Detailed info about each registered callback."""
        return [
            {
                "name": tc.name,
                "timescale": tc.timescale,
                "min_interval_s": tc.min_interval_s,
                "last_fired_at": tc.last_fired_at,
            }
            for tc in sorted(self._callbacks.values(), key=lambda c: c.name)
        ]

    # -- lifecycle --

    async def start(self) -> None:
        """Start the heartbeat loop. Idempotent."""
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="brain.heartbeat")

    async def stop(self) -> None:
        """Stop the heartbeat loop. Waits for current pulse to finish."""
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=self._interval_s + 2.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None

    # -- pulsing --

    async def pulse(self) -> int:
        """Fire one pulse manually. Returns count of callbacks that fired.

        Useful for tests and explicit nudges. Respects multi-rate intervals.
        """
        now = time.monotonic()
        self._pulse_count += 1
        self._last_pulse_at = now

        if not self._callbacks:
            return 0

        # Collect callbacks that are due
        due: list[TimedCallback] = [
            tc for tc in self._callbacks.values() if tc.is_due(now)
        ]

        if not due:
            return 0

        # Fire all due callbacks in parallel
        coros = [self._safe_call(tc) for tc in due]
        await asyncio.gather(*coros)

        # Update last_fired_at for callbacks that ran
        for tc in due:
            tc.last_fired_at = now

        return len(due)

    async def pulse_all(self) -> int:
        """Fire ALL callbacks regardless of interval. For testing only.

        Ignores timescale gating. Every registered callback fires.
        """
        now = time.monotonic()
        self._pulse_count += 1
        self._last_pulse_at = now

        if not self._callbacks:
            return 0

        all_cbs = list(self._callbacks.values())
        coros = [self._safe_call(tc) for tc in all_cbs]
        await asyncio.gather(*coros)

        for tc in all_cbs:
            tc.last_fired_at = now

        return len(all_cbs)

    # -- internals --

    async def _safe_call(self, tc: TimedCallback) -> None:
        """Run one callback. Never raise. Log and swallow exceptions."""
        try:
            await tc.callback()
        except Exception as exc:
            log.error("heartbeat callback %r failed: %s", tc.name, exc)

    async def _run(self) -> None:
        """Main loop. Pulse at fixed intervals until stopped."""
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_s)
                return  # stop was set
            except asyncio.TimeoutError:
                await self.pulse()


__all__ = [
    "Heartbeat",
    "PulseCallback",
    "TIMESCALE_DEFAULTS",
    "TimedCallback",
    "Timescale",
]
