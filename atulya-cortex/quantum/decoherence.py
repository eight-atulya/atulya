"""decoherence.py — the rollback supervisor.

Decoherence is the moment a wave function collapses: speculative work is
either committed (it becomes reality) or thrown away (it never happened).
This module is the supervisor that knows *when* to collapse:

- On graceful cortex shutdown -> rollback every open speculation.
- On a channel disconnect    -> rollback speculations bound to that channel.
- On an explicit cortex deny  -> rollback the speculations under it.

`Decoherence` is intentionally thin; the heavy lifting lives in
`superposition.py`. This file owns the *policy*: when speculation goes
away.

Naming voice: `Decoherence.collapse` / `bind`. `bind(channel, spec)` ties
a speculation to a channel; `collapse(channel)` rolls back everything
bound to it.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from quantum.superposition import Speculation, Superposition


class Decoherence:
    """Channel-scoped speculation supervisor."""

    def __init__(self, superposition: Superposition) -> None:
        self._super = superposition
        self._by_channel: dict[str, list[str]] = defaultdict(list)

    def bind(self, channel: str, spec: Speculation) -> None:
        self._by_channel[channel].append(spec.id)

    def channels(self) -> list[str]:
        return sorted(self._by_channel.keys())

    def specs_for(self, channel: str) -> list[str]:
        return list(self._by_channel.get(channel, []))

    async def collapse(self, channel: str) -> int:
        ids = list(self._by_channel.pop(channel, []))
        n = 0
        for sid in ids:
            spec = self._super._open.get(sid)
            if spec is None or spec.settled:
                continue
            await self._super.rollback(spec)
            n += 1
        return n

    async def collapse_all(self) -> int:
        n = 0
        for channel in list(self._by_channel.keys()):
            n += await self.collapse(channel)
        n += await self._super.rollback_all()
        return n

    def forget(self, ids: Iterable[str]) -> None:
        ids = set(ids)
        empty: list[str] = []
        for ch, lst in self._by_channel.items():
            self._by_channel[ch] = [i for i in lst if i not in ids]
            if not self._by_channel[ch]:
                empty.append(ch)
        for ch in empty:
            self._by_channel.pop(ch, None)


__all__ = ["Decoherence"]
