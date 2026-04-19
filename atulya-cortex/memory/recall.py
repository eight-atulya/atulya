"""recall.py — retrieves memories from the durable substrate.

Recall is the brain's "what do I know about this?" surface. It wraps
atulya-embed's `arecall` and converts the substrate's `RecallResult` rows
into cortex `Recollection` bus types.

Atulya does not return a relevance score per row — results come back ranked
by relevance. We synthesize a score by linear decay (1.0 -> 1/n over the
result list) so callers can prune downstream without losing rank order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

from cortex.bus import Budget, MemoryKind, Recollection
from memory.hippocampus import DEFAULT_BANK, kind_tag

if TYPE_CHECKING:  # pragma: no cover - typing only
    from atulya import AtulyaEmbedded


# Map cortex MemoryKind -> atulya substrate `type` filter where the mapping
# is unambiguous. Atulya's native types are world | experience | opinion |
# observation. Where the mapping is fuzzy (procedural / emotional) we rely on
# the cortex kind tag for filtering instead of the substrate type.
_KIND_TO_SUBSTRATE_TYPE: dict[MemoryKind, str] = {
    "episodic": "experience",
    "semantic": "world",
    "emotional": "opinion",
    # "procedural" intentionally absent — relies on tag filter.
}


class Recall:
    """Retrieves recollections from the durable substrate via atulya-embed."""

    def __init__(self, embedded: "AtulyaEmbedded", *, default_bank: str = DEFAULT_BANK) -> None:
        self._embedded = embedded
        self._default_bank = default_bank

    @property
    def default_bank(self) -> str:
        return self._default_bank

    async def recall(
        self,
        query: str,
        *,
        budget: Budget = "mid",
        kinds: Sequence[MemoryKind] | None = None,
        bank: str | None = None,
        top_k: int | None = None,
        extra_tags: list[str] | None = None,
    ) -> list[Recollection]:
        """Recall memories ranked by substrate relevance, returned as `Recollection` rows."""

        if not query or not query.strip():
            return []

        target_bank = bank or self._default_bank
        substrate_types: list[str] | None = None
        tag_filter: list[str] | None = None

        if kinds:
            mapped = [_KIND_TO_SUBSTRATE_TYPE[k] for k in kinds if k in _KIND_TO_SUBSTRATE_TYPE]
            if mapped:
                substrate_types = sorted(set(mapped))
            tag_filter = [kind_tag(k) for k in kinds]

        if extra_tags:
            tag_filter = list(tag_filter or []) + list(extra_tags)

        response = await self._embedded.arecall(
            bank_id=target_bank,
            query=query,
            types=substrate_types,
            budget=budget,
            tags=tag_filter,
        )

        results = list(getattr(response, "results", []) or [])
        if top_k is not None:
            results = results[: max(0, top_k)]

        recollections: list[Recollection] = []
        n = max(1, len(results))
        for idx, row in enumerate(results):
            text = getattr(row, "text", "") or ""
            substrate_type = getattr(row, "type", None) or "world"
            kind: MemoryKind = _substrate_type_to_kind(substrate_type, getattr(row, "tags", None))
            score = 1.0 - (idx / n)
            source = getattr(row, "document_id", None) or getattr(row, "id", None) or "atulya-embed"
            recollections.append(Recollection(kind=kind, text=text, score=score, source=str(source)))

        return recollections


def _substrate_type_to_kind(substrate_type: str, tags: list[str] | None) -> MemoryKind:
    """Reverse-map an atulya substrate `type` (and optional cortex tags) back to a MemoryKind."""

    if tags:
        for tag in tags:
            if tag.startswith("cortex:kind:"):
                kind_name = tag.split(":", 2)[2]
                if kind_name in {"episodic", "semantic", "procedural", "emotional"}:
                    return kind_name  # type: ignore[return-value]

    inverse = {
        "experience": "episodic",
        "world": "semantic",
        "opinion": "emotional",
        "observation": "semantic",
    }
    return inverse.get(substrate_type, "semantic")  # type: ignore[return-value]


__all__ = ["Recall"]
