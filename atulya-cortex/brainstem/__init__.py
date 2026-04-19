"""brainstem — the autonomic nervous system.

Four organs:
- `heartbeat.py`  — async cron loop (heart pulses on a schedule)
- `breathing.py`  — token + rate budget regulator (breath sets cadence)
- `reflexes.py`   — pre-cortex guards (DM pairing, allowlist, sandbox)
- `router.py`     — every Stimulus passes here on its way to the Cortex

This module declares the contract type and re-exports the concrete organs.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cortex.bus import Reflex, Stimulus


@runtime_checkable
class Reflexive(Protocol):
    """Anything that decides allow / deny / pair / sandbox before the cortex."""

    async def evaluate(self, stimulus: Stimulus) -> Reflex: ...


from brainstem.breathing import Breathing  # noqa: E402
from brainstem.heartbeat import Heartbeat, PulseCallback  # noqa: E402
from brainstem.reflexes import Allowlist, DMPairing, ReflexChain  # noqa: E402
from brainstem.router import (  # noqa: E402
    CortexCallable,
    MotorCallable,
    Router,
    RoutingOutcome,
)

__all__ = [
    "Allowlist",
    "Breathing",
    "CortexCallable",
    "DMPairing",
    "Heartbeat",
    "MotorCallable",
    "PulseCallback",
    "Reflexive",
    "ReflexChain",
    "Router",
    "RoutingOutcome",
]
