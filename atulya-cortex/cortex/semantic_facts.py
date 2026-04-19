"""semantic_facts.py — semantic memory. The neocortex's slow learner.

Episodic memory remembers *what happened*. Semantic memory remembers
*what is true* — durable propositional knowledge stripped of when,
where, who-said-it. "Anurag prefers terse answers" is a fact; "On
Tuesday at 3:14pm Anurag asked me to be terse" is an episode.

The mapping
-----------

Per-peer JSONL of `Fact` records:
`<root>/<safe_peer>.jsonl`

Each record is a small Pydantic-like dataclass with:
- `id`            — stable; used for upsert dedup
- `text`          — the propositional content, one short sentence
- `confidence`    — 0..1; consolidation may boost on repeated observation
- `source_episodes` — episode ids that produced/reinforced this fact
- `tags`          — free-form ("preference", "skill", "constraint", ...)

Why peer-scoped, not global
---------------------------

Most facts the brain learns are about a specific person ("Anurag works
in Bangalore", "Anurag's daughter is named Kuhi"). Mixing those into a
global pool would either leak across contacts (privacy regression) or
require per-row owner tags every time we recall (slow & error-prone).
Peer-scoped files are the cheapest way to make recall both fast and
private.

Upsert semantics
----------------

`upsert` deduplicates by exact `id` first, then by normalised-text
similarity. New observations of an existing fact bump confidence and
append their episode id to `source_episodes`; truly new facts get a
fresh id. Conflicts (e.g. an old fact contradicted by a new one) are
*not* auto-resolved — they sit side by side until consolidation or the
operator prunes them. That mirrors how humans hold contradictory
beliefs about people they're still figuring out.

Naming voice: `FactStore` is the noun; `upsert`, `facts_for`,
`render_for_prompt` are the verbs.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_stem(peer_key: str) -> str:
    s = (peer_key or "anon").strip().lower()
    s = re.sub(r"[^a-z0-9_.+-]+", "_", s)
    s = s.strip("._-") or "anon"
    return s[:96]


def _normalize(text: str) -> str:
    """Cheap normaliser for similarity dedup.

    Strip punctuation, collapse whitespace, lowercase. We'll compare
    Jaccard over token sets; a real semantic-similarity check would use
    embeddings but that's a future upgrade and not load-bearing for
    correctness here.
    """

    s = re.sub(r"[^a-zA-Z0-9\s]+", " ", text or "").strip().lower()
    return re.sub(r"\s+", " ", s)


def _jaccard(a: str, b: str) -> float:
    sa = set(a.split())
    sb = set(b.split())
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union


@dataclass(frozen=True)
class Fact:
    """One durable proposition the brain believes about a peer.

    The dataclass IS the wire format — `to_dict` / `from_dict` round-trip
    through JSON. `created_at` records first observation; `updated_at`
    moves forward every time the fact is reinforced so a `top_recent`
    style query can prefer beliefs the brain has touched lately.
    """

    id: str
    peer: str
    text: str
    confidence: float
    tags: tuple[str, ...]
    source_episodes: tuple[str, ...]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "peer": self.peer,
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "tags": list(self.tags),
            "source_episodes": list(self.source_episodes),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Fact":
        return cls(
            id=str(raw.get("id") or _new_id()),
            peer=str(raw.get("peer") or "anon"),
            text=str(raw.get("text") or "").strip(),
            confidence=max(0.0, min(1.0, float(raw.get("confidence") or 0.5))),
            tags=tuple(raw.get("tags") or ()),
            source_episodes=tuple(raw.get("source_episodes") or ()),
            created_at=str(raw.get("created_at") or _now_iso()),
            updated_at=str(raw.get("updated_at") or _now_iso()),
        )


def _new_id() -> str:
    return f"{int(time.time() * 1000):013d}-{uuid.uuid4().hex[:8]}"


# When two facts overlap by this much (Jaccard) we treat the new
# observation as a reinforcement of the existing fact rather than a
# distinct belief. Tuned for short single-sentence facts; raise for
# stricter dedup (more facts kept), lower for more aggressive merging.
DEFAULT_DEDUP_THRESHOLD: float = 0.7


@dataclass
class FactStore:
    """File-backed per-peer semantic-fact memory.

    Contract: one JSONL per peer. Reads load the whole file (small);
    writes use a per-peer lock and an atomic rewrite. The trade-off
    matches `episodes.py`: simple, durable, restorable from a manual
    edit, no external service required.
    """

    root: Path
    dedup_threshold: float = DEFAULT_DEDUP_THRESHOLD
    _locks: dict[str, threading.Lock] = field(default_factory=dict, init=False, repr=False)
    _global_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _lock(self, peer: str) -> threading.Lock:
        with self._global_lock:
            lock = self._locks.get(peer)
            if lock is None:
                lock = threading.Lock()
                self._locks[peer] = lock
        return lock

    def _path(self, peer: str) -> Path:
        return self.root / f"{_safe_stem(peer)}.jsonl"

    # ---- read ------------------------------------------------------------

    def facts_for(self, peer: str) -> list[Fact]:
        path = self._path(peer)
        if not path.exists():
            return []
        out: list[Fact] = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(Fact.from_dict(json.loads(line)))
                    except (json.JSONDecodeError, ValueError, TypeError) as exc:
                        logger.debug("facts: skipping malformed line in %s: %s", path, exc)
                        continue
        except FileNotFoundError:
            return []
        return out

    def list_peers(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.stem for p in self.root.glob("*.jsonl"))

    # ---- write -----------------------------------------------------------

    def upsert(
        self,
        peer: str,
        *,
        text: str,
        tags: Iterable[str] = (),
        source_episodes: Iterable[str] = (),
        confidence: float = 0.7,
    ) -> Fact | None:
        """Insert a fact or merge it into an existing similar one.

        Returns the resulting `Fact` (whether newly created or merged),
        or `None` if the input text was empty after normalisation.

        Merge semantics:
        - If a near-duplicate exists (Jaccard >= dedup_threshold), bump
          its confidence by `0.1 * confidence`, append the new source
          episodes, refresh `updated_at`, and return the merged fact.
        - Otherwise, create a fresh fact with `created_at = updated_at`.
        """

        clean = (text or "").strip()
        if not clean or not _normalize(clean):
            return None

        with self._lock(peer):
            facts = self.facts_for(peer)
            target_idx = self._find_similar(facts, clean)
            now = _now_iso()
            if target_idx is None:
                fact = Fact(
                    id=_new_id(),
                    peer=peer,
                    text=clean,
                    confidence=max(0.0, min(1.0, float(confidence))),
                    tags=tuple(t for t in tags if t),
                    source_episodes=tuple(e for e in source_episodes if e),
                    created_at=now,
                    updated_at=now,
                )
                facts.append(fact)
            else:
                existing = facts[target_idx]
                merged_eps = list(existing.source_episodes)
                for e in source_episodes:
                    if e and e not in merged_eps:
                        merged_eps.append(e)
                merged_tags = list(existing.tags)
                for t in tags:
                    if t and t not in merged_tags:
                        merged_tags.append(t)
                bumped = min(1.0, existing.confidence + 0.1 * float(confidence))
                fact = Fact(
                    id=existing.id,
                    peer=peer,
                    text=existing.text,  # keep the original phrasing; new evidence reinforces it
                    confidence=bumped,
                    tags=tuple(merged_tags),
                    source_episodes=tuple(merged_eps),
                    created_at=existing.created_at,
                    updated_at=now,
                )
                facts[target_idx] = fact

            self._rewrite(peer, facts)
            return fact

    def forget(self, peer: str, *, fact_id: str) -> bool:
        with self._lock(peer):
            facts = self.facts_for(peer)
            new_facts = [f for f in facts if f.id != fact_id]
            if len(new_facts) == len(facts):
                return False
            self._rewrite(peer, new_facts)
            return True

    def clear(self, peer: str) -> int:
        path = self._path(peer)
        if not path.exists():
            return 0
        size = path.stat().st_size
        with self._lock(peer):
            try:
                path.unlink()
            except FileNotFoundError:
                return 0
        return size

    # ---- prompt rendering -----------------------------------------------

    def render_for_prompt(
        self,
        peer: str,
        *,
        top_k: int = 8,
        min_confidence: float = 0.4,
        label: str = "What I know about this peer",
    ) -> str:
        """Format the top-k highest-confidence facts as a system-prompt block.

        Ordering: confidence desc, then `updated_at` desc as a tiebreaker
        so recently-reinforced beliefs win over equally-confident stale
        ones. Facts below `min_confidence` are dropped to keep the prompt
        tight on small models.
        """

        facts = [f for f in self.facts_for(peer) if f.confidence >= min_confidence]
        if not facts:
            return ""
        facts.sort(key=lambda f: (f.confidence, f.updated_at), reverse=True)
        chosen = facts[: max(0, top_k)]
        if not chosen:
            return ""
        lines = [f"{label}:"]
        for f in chosen:
            tag_part = f" ({', '.join(f.tags)})" if f.tags else ""
            lines.append(f"- {f.text}{tag_part}")
        return "\n".join(lines)

    # ---- internal --------------------------------------------------------

    def _find_similar(self, facts: list[Fact], new_text: str) -> int | None:
        norm_new = _normalize(new_text)
        best_idx: int | None = None
        best_score: float = self.dedup_threshold
        for i, f in enumerate(facts):
            score = _jaccard(norm_new, _normalize(f.text))
            if score >= best_score:
                best_idx = i
                best_score = score
        return best_idx

    def _rewrite(self, peer: str, facts: list[Fact]) -> None:
        path = self._path(peer)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for f in facts:
                fh.write(json.dumps(f.to_dict(), ensure_ascii=False) + "\n")
        tmp.replace(path)


__all__ = [
    "DEFAULT_DEDUP_THRESHOLD",
    "Fact",
    "FactStore",
]
