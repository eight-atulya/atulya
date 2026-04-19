"""emotional.py — read-only adapter onto bank disposition.

Emotional memory is the brain's *affect* — a per-bank disposition with mood,
arousal, and free-form traits. Cortex reads disposition to bias language
output (e.g., persona tone). It does NOT mutate disposition; that is set by
operators or by long-running consolidation jobs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cortex.bus import Disposition

if TYPE_CHECKING:  # pragma: no cover - typing only
    from atulya import AtulyaEmbedded


class EmotionalMemory:
    """Reads bank disposition through the atulya-embed bank-config API."""

    def __init__(self, embedded: "AtulyaEmbedded") -> None:
        self._embedded = embedded

    async def disposition_for(self, bank: str) -> Disposition:
        """Return the cortex Disposition for the given bank.

        Atulya's bank config exposes `disposition_skepticism`, `_literalism`,
        `_empathy` as integers in [0, 100]. We project these onto cortex's
        `mood` (empathy → mood) and `arousal` (skepticism → arousal). The full
        raw config is preserved under `traits` for callers that want it.
        """

        try:
            cfg: dict[str, Any] = self._embedded.get_bank_config(bank)
        except Exception:
            return Disposition()

        config = cfg.get("config") or cfg
        empathy = _safe_float(config.get("disposition_empathy"))
        skepticism = _safe_float(config.get("disposition_skepticism"))
        literalism = _safe_float(config.get("disposition_literalism"))

        mood = _to_unit(empathy) if empathy is not None else 0.0
        arousal = _to_unit(skepticism) if skepticism is not None else 0.0

        traits = {
            "empathy": empathy,
            "skepticism": skepticism,
            "literalism": literalism,
            "raw": cfg,
        }
        return Disposition(mood=mood, arousal=arousal, traits=traits)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_unit(value: float) -> float:
    """Project [0, 100] -> [-1.0, 1.0] (50 -> 0.0)."""

    return max(-1.0, min(1.0, (value - 50.0) / 50.0))


__all__ = ["EmotionalMemory"]
