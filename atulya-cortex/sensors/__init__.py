"""sensors — perception in.

Public surface:
- `Sensor` (Protocol) — every sensor implements this.
- `Terminal`          — the screen-eye (TUI).
- `TelegramEar`       — telegram inbound (optional dep: python-telegram-bot).
- `WhatsAppEar`       — WhatsApp inbound (backend-agnostic; ships Baileys + Cloud API).
- `Ear`               — placeholder microphone sensor (v2).
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from cortex.bus import Stimulus


@runtime_checkable
class Sensor(Protocol):
    """Contract every sensor implements.

    Lifecycle:
        await sensor.awaken()
        async for stim in sensor.perceive():
            ...
        await sensor.rest()
    """

    async def awaken(self) -> None: ...

    def perceive(self) -> AsyncIterator[Stimulus]: ...

    async def rest(self) -> None: ...


from sensors.hearing import Ear  # noqa: E402
from sensors.telegram import TelegramEar  # noqa: E402
from sensors.tui import Terminal  # noqa: E402
from sensors.whatsapp import (  # noqa: E402
    BaileysBackend,
    WhatsAppBackend,
    WhatsAppCloudBackend,
    WhatsAppEar,
)

__all__ = [
    "BaileysBackend",
    "Ear",
    "Sensor",
    "TelegramEar",
    "Terminal",
    "WhatsAppBackend",
    "WhatsAppCloudBackend",
    "WhatsAppEar",
]
