"""in_memory.py — fast in-process MemoryStore for tests and CI.

`InMemorySubstrate` implements the same Protocol as `AtulyaSubstrate` but
keeps everything in a Python dict. No daemon, no network, no LLM. Used by
all later batches' tests so CI stays under one second.

Recall is a token-overlap search (Jaccard on lowercased word-sets). It is
intentionally dumb — we are testing wiring, not retrieval quality. For
retrieval quality we use the real daemon.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Sequence

from cortex.bus import Disposition, MemoryKind, Recollection, Stimulus
from memory.hippocampus import DEFAULT_BANK, kind_tag


class _Row:
    __slots__ = ("id", "text", "kind", "tags", "bank")

    def __init__(self, *, text: str, kind: MemoryKind, tags: list[str], bank: str) -> None:
        self.id = uuid.uuid4().hex
        self.text = text
        self.kind = kind
        self.tags = list(tags)
        self.bank = bank


class InMemorySubstrate:
    """Token-overlap, in-process MemoryStore. Satisfies the same Protocol as AtulyaSubstrate."""

    def __init__(self, *, default_bank: str = DEFAULT_BANK) -> None:
        self._default_bank = default_bank
        self._rows: dict[str, list[_Row]] = defaultdict(list)
        self._dispositions: dict[str, Disposition] = {}

    @property
    def default_bank(self) -> str:
        return self._default_bank

    async def encode(
        self,
        stimulus: Stimulus,
        *,
        kind: MemoryKind,
        bank: str | None = None,
    ) -> dict:
        target_bank = bank or self._default_bank
        text = (stimulus.text or "").strip()
        if not text:
            return {"skipped": True, "reason": "empty stimulus text"}
        tags = [kind_tag(kind), f"cortex:channel:{stimulus.channel}", f"cortex:sender:{stimulus.sender}"]
        row = _Row(text=text, kind=kind, tags=tags, bank=target_bank)
        self._rows[target_bank].append(row)
        return {"ok": True, "bank_id": target_bank, "kind": kind, "id": row.id, "tags": tags}

    async def encode_text(
        self,
        text: str,
        *,
        kind: MemoryKind,
        bank: str | None = None,
        extra_tags: list[str] | None = None,
    ) -> dict:
        target_bank = bank or self._default_bank
        text = (text or "").strip()
        if not text:
            return {"skipped": True, "reason": "empty text"}
        tags = [kind_tag(kind)] + list(extra_tags or [])
        row = _Row(text=text, kind=kind, tags=tags, bank=target_bank)
        self._rows[target_bank].append(row)
        return {"ok": True, "bank_id": target_bank, "kind": kind, "id": row.id, "tags": tags}

    async def recall(
        self,
        query: str,
        *,
        budget: str = "mid",
        kinds: Sequence[MemoryKind] | None = None,
        bank: str | None = None,
    ) -> list[Recollection]:
        if not query or not query.strip():
            return []
        target_bank = bank or self._default_bank
        wanted_kinds = set(kinds) if kinds else None
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        scored: list[tuple[float, _Row]] = []
        for row in self._rows.get(target_bank, []):
            if wanted_kinds is not None and row.kind not in wanted_kinds:
                continue
            r_tokens = _tokenize(row.text)
            if not r_tokens:
                continue
            inter = len(q_tokens & r_tokens)
            if inter == 0:
                continue
            union = len(q_tokens | r_tokens)
            score = inter / union if union else 0.0
            scored.append((score, row))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        cap = _budget_cap(budget)
        scored = scored[:cap]

        return [Recollection(kind=row.kind, text=row.text, score=score, source=row.id) for score, row in scored]

    async def disposition_for(self, bank: str) -> Disposition:
        return self._dispositions.get(bank, Disposition())

    def set_disposition(self, bank: str, disposition: Disposition) -> None:
        self._dispositions[bank] = disposition

    def reset(self) -> None:
        self._rows.clear()
        self._dispositions.clear()


def _tokenize(text: str) -> set[str]:
    return {w for w in text.lower().split() if w}


def _budget_cap(budget: str) -> int:
    return {"low": 3, "small": 3, "mid": 8, "large": 24}.get(budget, 8)


__all__ = ["InMemorySubstrate"]
