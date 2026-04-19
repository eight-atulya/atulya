"""messaging.py — the `Reply` motor (channel egress).

`Reply` is the motor that sends an `Intent` back to the channel a `Stimulus`
came from. It does not own transports; it routes to one of the registered
egress callables (one per channel prefix: `tui:`, `telegram:`, `whatsapp:`).

Every channel prefix has exactly one egress callable; registering a second
replaces the first (the brain has one mouth per ear).

Naming voice: `Reply.prepare` / `act` / `recover`.
"""

from __future__ import annotations

import time
from typing import Awaitable, Callable

from cortex.bus import ActionResult, Intent

EgressCallable = Callable[[str, str, str], Awaitable[None]]
"""(channel, target, text) -> None where target is the suffix after the prefix."""


class Reply:
    """Channel-aware egress motor."""

    def __init__(self, egress: dict[str, EgressCallable] | None = None) -> None:
        self._egress: dict[str, EgressCallable] = {}
        for prefix, fn in (egress or {}).items():
            self.register(prefix, fn)

    def register(self, channel_prefix: str, egress: EgressCallable) -> None:
        if not channel_prefix.endswith(":"):
            channel_prefix = f"{channel_prefix}:"
        self._egress[channel_prefix] = egress

    def channels(self) -> list[str]:
        return sorted(self._egress.keys())

    async def prepare(self) -> None:
        return None

    async def recover(self) -> None:
        return None

    async def act(self, intent: Intent) -> ActionResult:
        started = time.monotonic()
        if intent.action.kind != "reply":
            return ActionResult(
                ok=False,
                detail=f"Reply motor cannot handle action.kind={intent.action.kind!r}",
                artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
            )
        text = str(intent.action.payload.get("text", "")).strip()
        if not text:
            return ActionResult(
                ok=False,
                detail="reply payload missing 'text'",
                artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
            )
        if not intent.channel:
            return ActionResult(
                ok=False,
                detail="reply intent missing channel",
                artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
            )

        prefix, _, target = intent.channel.partition(":")
        prefix_with_colon = f"{prefix}:"
        egress = self._egress.get(prefix_with_colon)
        if egress is None:
            return ActionResult(
                ok=False,
                detail=f"no egress registered for channel prefix {prefix_with_colon!r}",
                artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
            )
        try:
            await egress(intent.channel, target, text)
        except Exception as exc:
            return ActionResult(
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
            )
        return ActionResult(
            ok=True,
            artifact={
                "channel": intent.channel,
                "chars": len(text),
                "elapsed_ms": (time.monotonic() - started) * 1000.0,
            },
        )


__all__ = ["EgressCallable", "Reply"]
