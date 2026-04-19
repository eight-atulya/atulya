"""hearing.py — the literal ear sensor (microphone).

v1 ships only the contract; the body is `NotImplementedError("v2")`. Voice
input is a v2 feature; declaring the interface now keeps the biomimetic
voice consistent and gives `dream/skill_distill.py` a stable type to
reference if a future skill grows around audio input.
"""

from __future__ import annotations

from typing import AsyncIterator

from cortex.bus import Stimulus

CHANNEL_PREFIX = "voice:"


class Ear:
    """Microphone sensor — placeholder for v2.

    Naming voice: `Ear.tune_in` / `hear` / `tune_out`. Body raises until
    we wire in WebRTC / sounddevice in a later sprint.
    """

    def __init__(self, *, peer: str = "local") -> None:
        self._peer = peer

    @property
    def channel(self) -> str:
        return f"{CHANNEL_PREFIX}{self._peer}"

    async def awaken(self) -> None:
        raise NotImplementedError("hearing.py: microphone capture is a v2 feature")

    async def perceive(self) -> AsyncIterator[Stimulus]:
        raise NotImplementedError("hearing.py: microphone capture is a v2 feature")
        if False:  # pragma: no cover - satisfies the AsyncIterator return type
            yield Stimulus(channel=self.channel, sender=self._peer)

    async def rest(self) -> None:
        return None


__all__ = ["CHANNEL_PREFIX", "Ear"]
