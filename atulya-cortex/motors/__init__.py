"""motors — action out.

Every concrete motor implements the `Motor` Protocol. Anatomical naming:

- `Reply` (messaging)             — egresses an Intent back to the channel
                                    a Stimulus came from.
- `Mouth` (speech, TTS)           — turns text into spoken audio.
- `Hand`  (fine_motor_skills)     — runs a small, sandboxed toolset
                                    (bash, read/write/edit, web_fetch).
- `Body`  (movement, subagents)   — spawns a sub-cortex on a focused goal.

Lifecycle is `prepare` / `act` / `recover`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cortex.bus import ActionResult, Intent


@runtime_checkable
class Motor(Protocol):
    """Contract every motor implements."""

    async def prepare(self) -> None: ...

    async def act(self, intent: Intent) -> ActionResult: ...

    async def recover(self) -> None: ...


from motors.fine_motor_skills import Hand  # noqa: E402
from motors.messaging import Reply  # noqa: E402
from motors.movement import Body  # noqa: E402
from motors.speech import Mouth  # noqa: E402

__all__ = [
    "Body",
    "Hand",
    "Motor",
    "Mouth",
    "Reply",
]
