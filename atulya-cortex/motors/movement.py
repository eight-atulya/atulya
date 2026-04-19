"""movement.py — the `Body` motor (delegation to subagents).

`Body` spawns a sub-cortex on a focused goal and returns its distilled
answer. In v1 a "subagent" is just another `Cortex.reflect`-style call
running with a fresh, narrowed `Stimulus`.

Payload contract:

    intent.action.payload == {"goal": <str>, "tools": [<tool_name>, ...]}

Naming voice: `Body.prepare` / `act` / `recover`. We call it `Body` because
every other motor uses one *part* of it; subagents use the whole thing.
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from cortex.bus import ActionResult, Intent, Stimulus

Reflector = Callable[[Stimulus], Awaitable[str]]


class Body:
    """Subagent-spawning motor."""

    SUBAGENT_CHANNEL_PREFIX = "subagent:"

    def __init__(self, reflector: Reflector, *, max_concurrent: int = 4) -> None:
        self._reflector = reflector
        self._semaphore = asyncio.Semaphore(max(1, int(max_concurrent)))
        self._max_concurrent = max(1, int(max_concurrent))

    async def prepare(self) -> None:
        return None

    async def recover(self) -> None:
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

    async def act(self, intent: Intent) -> ActionResult:
        started = time.monotonic()
        if intent.action.kind != "delegate":
            return ActionResult(
                ok=False,
                detail=f"Body motor cannot handle action.kind={intent.action.kind!r}",
                artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
            )
        goal = str(intent.action.payload.get("goal", "")).strip()
        if not goal:
            return ActionResult(
                ok=False,
                detail="delegate payload missing 'goal'",
                artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
            )
        tools = list(intent.action.payload.get("tools") or [])
        sub_stim = Stimulus(
            channel=f"{self.SUBAGENT_CHANNEL_PREFIX}{intent.channel}",
            sender="parent-cortex",
            text=goal,
            raw={"parent_channel": intent.channel, "tools": tools},
        )
        async with self._semaphore:
            try:
                answer = await self._reflector(sub_stim)
            except Exception as exc:
                return ActionResult(
                    ok=False,
                    detail=f"{type(exc).__name__}: {exc}",
                    artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
                )
        return ActionResult(
            ok=True,
            artifact={
                "answer": answer,
                "subagent_channel": sub_stim.channel,
                "elapsed_ms": (time.monotonic() - started) * 1000.0,
            },
        )


__all__ = ["Body", "Reflector"]
