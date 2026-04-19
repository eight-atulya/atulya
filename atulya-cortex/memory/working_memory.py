"""working_memory.py — the only memory store that does NOT round-trip atulya-embed.

WorkingMemory holds two things:

1. A bounded conversation buffer per (channel, sender) — the last N stimuli
   and the cortex's last N intents, so a turn can include the recent dialogue
   without paying a substrate roundtrip every time.
2. A general-purpose LRU keyed by string — used by `silo/llm_cache.py` for
   in-process completion caching when a disk cache miss would still be too
   slow.

Working memory is intentionally non-durable. It evaporates on process exit.
Anything we want to remember tomorrow goes through the Hippocampus.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from threading import Lock
from typing import Any, Iterable

from cortex.bus import Intent, Stimulus

DEFAULT_TURN_BUFFER = 16
DEFAULT_LRU_CAPACITY = 256


class _ConversationBuffer:
    """Bounded FIFO of (stimulus, optional intent) tuples for one (channel, sender)."""

    __slots__ = ("_max", "_items")

    def __init__(self, max_turns: int) -> None:
        self._max = max_turns
        self._items: deque[tuple[Stimulus, Intent | None]] = deque(maxlen=max_turns)

    def append(self, stimulus: Stimulus, intent: Intent | None = None) -> None:
        self._items.append((stimulus, intent))

    def attach_intent(self, intent: Intent) -> None:
        """Attach an intent to the most-recent stimulus (after the cortex finished reflecting)."""

        if not self._items:
            return
        last_stim, _ = self._items[-1]
        self._items[-1] = (last_stim, intent)

    def turns(self) -> Iterable[tuple[Stimulus, Intent | None]]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)


class WorkingMemory:
    """In-process memory: conversation buffers + general-purpose LRU.

    Thread-safe. All mutating operations take a single lock; the LRU and
    buffer maps are dict-backed and cheap.
    """

    def __init__(
        self,
        *,
        turn_buffer: int = DEFAULT_TURN_BUFFER,
        lru_capacity: int = DEFAULT_LRU_CAPACITY,
    ) -> None:
        self._turn_buffer = turn_buffer
        self._lru_capacity = lru_capacity
        self._buffers: dict[tuple[str, str], _ConversationBuffer] = {}
        self._lru: OrderedDict[str, Any] = OrderedDict()
        self._lock = Lock()

    # ------------------------------------------------------------------ buffers

    def _key(self, stimulus: Stimulus) -> tuple[str, str]:
        return (stimulus.channel, stimulus.sender)

    def remember_stimulus(self, stimulus: Stimulus) -> None:
        with self._lock:
            buf = self._buffers.get(self._key(stimulus))
            if buf is None:
                buf = _ConversationBuffer(self._turn_buffer)
                self._buffers[self._key(stimulus)] = buf
            buf.append(stimulus, None)

    def attach_intent(self, intent: Intent) -> None:
        with self._lock:
            buf = self._buffers.get((intent.channel, intent.sender))
            if buf is not None:
                buf.attach_intent(intent)

    def recent_turns(
        self,
        channel: str,
        sender: str,
    ) -> list[tuple[Stimulus, Intent | None]]:
        with self._lock:
            buf = self._buffers.get((channel, sender))
            return list(buf.turns()) if buf is not None else []

    def turn_count(self, channel: str, sender: str) -> int:
        with self._lock:
            buf = self._buffers.get((channel, sender))
            return len(buf) if buf is not None else 0

    def forget_conversation(self, channel: str, sender: str) -> None:
        with self._lock:
            self._buffers.pop((channel, sender), None)

    # --------------------------------------------------------------------- LRU

    def lru_get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._lru:
                self._lru.move_to_end(key)
                return self._lru[key]
            return default

    def lru_put(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._lru:
                self._lru.move_to_end(key)
                self._lru[key] = value
                return
            self._lru[key] = value
            while len(self._lru) > self._lru_capacity:
                self._lru.popitem(last=False)

    def lru_evict(self, key: str) -> None:
        with self._lock:
            self._lru.pop(key, None)

    def lru_size(self) -> int:
        with self._lock:
            return len(self._lru)

    def lru_clear(self) -> None:
        with self._lock:
            self._lru.clear()

    # ----------------------------------------------------------- introspection

    def conversation_count(self) -> int:
        with self._lock:
            return len(self._buffers)

    def reset(self) -> None:
        with self._lock:
            self._buffers.clear()
            self._lru.clear()


__all__ = ["DEFAULT_LRU_CAPACITY", "DEFAULT_TURN_BUFFER", "WorkingMemory"]
