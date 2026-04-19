"""breathing.py — the token + rate budget regulator.

Breath sets the cadence of LLM calls. v1 implements two budgets:

- A **token budget** with a refilling reservoir per `window_s` (think: a
  carbon-dioxide ceiling for an hour-long breath cycle).
- A **per-channel rate** in messages-per-second to absorb spam without
  starving the cortex.

`Breathing.may_speak(channel, est_tokens)` returns True/False *and* records
the consumption when it returns True. The cortex consults breath before
every LLM call.

Naming voice: `Breathing.may_speak` / `inhale` / `exhale`.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class _ChannelBucket:
    last_seen: float = 0.0
    recent: deque[float] = field(default_factory=deque)


class Breathing:
    """Token reservoir + per-channel rate limiter."""

    def __init__(
        self,
        *,
        token_budget: int = 200_000,
        window_s: float = 3600.0,
        per_channel_rate_per_s: float = 1.0,
        per_channel_burst: int = 5,
    ) -> None:
        if token_budget <= 0:
            raise ValueError("token_budget must be > 0")
        if window_s <= 0:
            raise ValueError("window_s must be > 0")
        if per_channel_rate_per_s <= 0:
            raise ValueError("per_channel_rate_per_s must be > 0")
        self._token_budget = int(token_budget)
        self._window_s = float(window_s)
        self._per_channel_rate = float(per_channel_rate_per_s)
        self._per_channel_burst = max(1, int(per_channel_burst))
        self._tokens_consumed: deque[tuple[float, int]] = deque()
        self._channels: dict[str, _ChannelBucket] = {}

    def _gc_tokens(self, now: float) -> None:
        cutoff = now - self._window_s
        while self._tokens_consumed and self._tokens_consumed[0][0] < cutoff:
            self._tokens_consumed.popleft()

    def remaining_tokens(self, *, now: float | None = None) -> int:
        ts = time.monotonic() if now is None else now
        self._gc_tokens(ts)
        spent = sum(n for _, n in self._tokens_consumed)
        return max(0, self._token_budget - spent)

    def _channel_clean(self, bucket: _ChannelBucket, now: float) -> None:
        cutoff = now - 1.0  # one second window for burst tracking
        while bucket.recent and bucket.recent[0] < cutoff:
            bucket.recent.popleft()

    def may_speak(self, channel: str, est_tokens: int = 0) -> bool:
        """True if both budget and rate allow; records consumption when True."""

        if est_tokens < 0:
            est_tokens = 0
        now = time.monotonic()
        if self.remaining_tokens(now=now) < est_tokens:
            return False
        bucket = self._channels.setdefault(channel, _ChannelBucket())
        self._channel_clean(bucket, now)
        if len(bucket.recent) >= self._per_channel_burst:
            min_gap = 1.0 / self._per_channel_rate
            if now - bucket.last_seen < min_gap:
                return False
        bucket.recent.append(now)
        bucket.last_seen = now
        if est_tokens > 0:
            self._tokens_consumed.append((now, est_tokens))
        return True

    def inhale(self, tokens: int) -> None:
        """Refund tokens (e.g. when an LLM call is cancelled before it ran)."""

        if tokens <= 0 or not self._tokens_consumed:
            return
        remaining = tokens
        new_back: list[tuple[float, int]] = []
        while self._tokens_consumed and remaining > 0:
            ts, n = self._tokens_consumed.pop()
            if n <= remaining:
                remaining -= n
            else:
                new_back.append((ts, n - remaining))
                remaining = 0
        for entry in reversed(new_back):
            self._tokens_consumed.append(entry)

    def exhale(self, tokens: int) -> None:
        """Record tokens after the fact (e.g. when prompt size is only known post-render)."""

        if tokens <= 0:
            return
        self._tokens_consumed.append((time.monotonic(), tokens))


__all__ = ["Breathing"]
