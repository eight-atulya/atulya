"""consolidation.py — heartbeat-driven mental-model consolidation.

A `Consolidation` dreamer fires on every brainstem `Heartbeat` pulse. Its
job: ask `atulya-api` to refresh the bank's mental models in **delta mode**
(the feature shipped in the previous sprint), so the brain's long-term
self-model improves without re-running the whole render.

The trigger is HTTP-shaped (PUT/POST against the atulya-api control plane)
so this module stays decoupled from the api's internals. The wire format is
the `MentalModelTrigger` Pydantic model exposed by atulya-api at
`/api/banks/{bank}/mental-models/{id}/refresh`. We send `{"mode": "delta"}`.

Pacing:
- One refresh attempt per pulse, at most.
- Per-model cooldown (`min_interval_s`, default 5 minutes) so a fast
  heartbeat does not hammer the api.
- Per-pulse work cap (`per_pulse_cap`, default 3 mental models) so a single
  pulse never blows the LLM token budget.

Naming voice: `Consolidation.dream` is the verb (the Dreamer Protocol).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx

RefreshCallable = Callable[[str, str], Awaitable[dict[str, Any]]]
"""(bank_id, mental_model_id) -> response dict from atulya-api."""


@dataclass
class ConsolidationStats:
    pulses: int = 0
    refreshes_attempted: int = 0
    refreshes_ok: int = 0
    refreshes_failed: int = 0
    skipped_cooldown: int = 0
    last_pulse_at: float | None = None
    last_error: str | None = None
    per_model_last_seen: dict[str, float] = field(default_factory=dict)


class Consolidation:
    """Heartbeat-driven mental-model delta refresher."""

    def __init__(
        self,
        *,
        bank_id: str,
        mental_model_ids: list[str],
        api_base_url: str = "http://localhost:8000",
        api_key: str | None = None,
        min_interval_s: float = 300.0,
        per_pulse_cap: int = 3,
        refresh: RefreshCallable | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not mental_model_ids:
            raise ValueError("Consolidation needs at least one mental_model_id")
        self._bank_id = bank_id
        self._mental_model_ids = list(mental_model_ids)
        self._api_base_url = api_base_url.rstrip("/")
        self._api_key = api_key
        self._min_interval_s = float(min_interval_s)
        self._per_pulse_cap = max(1, int(per_pulse_cap))
        self._refresh_override = refresh
        self._client = client
        self._owned_client = client is None
        self.stats = ConsolidationStats()

    async def aclose(self) -> None:
        if self._owned_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _client_or_make(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    async def _refresh_one(self, model_id: str) -> dict[str, Any]:
        if self._refresh_override is not None:
            return await self._refresh_override(self._bank_id, model_id)
        url = f"{self._api_base_url}/api/banks/{self._bank_id}/mental-models/{model_id}/refresh"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        client = self._client_or_make()
        resp = await client.post(url, headers=headers, json={"mode": "delta"})
        if resp.status_code >= 400:
            raise RuntimeError(f"refresh failed HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}

    async def dream(self) -> None:
        """One pulse of consolidation work."""

        self.stats.pulses += 1
        self.stats.last_pulse_at = time.monotonic()
        now = time.monotonic()
        attempted_this_pulse = 0
        for model_id in self._mental_model_ids:
            if attempted_this_pulse >= self._per_pulse_cap:
                break
            last = self.stats.per_model_last_seen.get(model_id, 0.0)
            if now - last < self._min_interval_s:
                self.stats.skipped_cooldown += 1
                continue
            self.stats.refreshes_attempted += 1
            attempted_this_pulse += 1
            try:
                await self._refresh_one(model_id)
                self.stats.refreshes_ok += 1
                self.stats.per_model_last_seen[model_id] = now
            except Exception as exc:
                self.stats.refreshes_failed += 1
                self.stats.last_error = f"{type(exc).__name__}: {exc}"


__all__ = ["Consolidation", "ConsolidationStats", "RefreshCallable"]
