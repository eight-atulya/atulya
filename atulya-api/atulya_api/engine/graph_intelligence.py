"""
Graph intelligence read models for the control plane.

This module lifts raw memory-unit evidence into a higher-level state graph that
surfaces meaningful changes, contradictions, and stale assumptions.

Reuses:
  - embedding_similarity.cosine_similarity  — semantic dedup + contradiction detection
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from itertools import combinations
from typing import Literal

from pydantic import BaseModel, Field

from .embedding_similarity import cosine_similarity

NodeKind = Literal["entity", "topic"]
NodeStatus = Literal["stable", "changed", "contradictory", "stale"]
ChangeType = Literal["change", "contradiction", "stale"]
PathStepKind = Literal["node", "event", "memory"]

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "to",
    "was",
    "were",
    "will",
    "with",
}
_NEGATION_MARKERS = {
    # Hard negations — explicitly deny the claim
    "not",
    "no",
    "never",
    "without",
    # State-exit verbs — subject explicitly stopped/abandoned the state
    "stopped",
    "quit",
    "left",
    "gave",
    "resigned",
    "retired",
    "ended",
    "cancelled",
    "abandoned",
    "removed",
    "deleted",
    "closed",
    "rejected",
    "handed",
    # Explicit past-state labels (not past tense — only when used as adjectives)
    "former",
    "ex",
    "previously",
    # NOTE: "was/were/had" deliberately omitted — past tense IS NOT negation.
    # "Anurag was the architect" and "never touched the code" would both
    # trigger if we include "was", making both sides negated → no contradiction.
    # NOTE: "stepped/moved/transitioned/dropped/switched" omitted — technical metrics
    # and lifecycle changes should not trigger negation detection.
}


class GraphEvidenceUnit(BaseModel):
    id: str
    text: str
    fact_type: str
    embedding: list[float] | None = None
    context: str | None = None
    occurred_start: datetime | None = None
    mentioned_at: datetime | None = None
    created_at: datetime | None = None
    proof_count: int = 0
    access_count: int = 0
    tags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    source_memory_ids: list[str] = Field(default_factory=list)
    # Document-level grouping key: units sharing the same chunk_id prefix (up to the last
    # underscore+index) belong to the same retain document and are "co-authored".
    chunk_id: str | None = None

    def effective_timestamp(self) -> datetime | None:
        return self.occurred_start or self.mentioned_at or self.created_at

    def doc_key(self) -> str | None:
        """Extract document-level key from chunk_id (strips trailing _<index>).

        chunk_id format: ``<bank_id>_<doc_uuid>_<chunk_index>``
        Two units with the same doc_key were created from the same retain document
        and are treated as co-authored (same source context).
        """
        if not self.chunk_id:
            return None
        # Strip the trailing _<index> suffix — everything up to the last underscore
        idx = self.chunk_id.rfind("_")
        return self.chunk_id[:idx] if idx > 0 else self.chunk_id


class GraphStateNode(BaseModel):
    id: str
    title: str
    kind: NodeKind
    subtitle: str | None = None
    current_state: str
    status: NodeStatus
    status_reason: str
    confidence: float
    change_score: float
    last_changed_at: str | None = None
    primary_timestamp: str | None = None
    evidence_count: int
    tags: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class GraphRelationEdge(BaseModel):
    id: str
    source_id: str
    target_id: str
    relation_type: str
    strength: float
    evidence_count: int


class GraphChangeEvent(BaseModel):
    id: str
    node_id: str
    change_type: ChangeType
    before_state: str | None = None
    after_state: str
    confidence: float
    time_window: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    summary: str


class GraphEvidencePathStep(BaseModel):
    kind: PathStepKind
    id: str
    label: str
    timestamp: str | None = None


class GraphIntelligenceResponse(BaseModel):
    nodes: list[GraphStateNode]
    edges: list[GraphRelationEdge]
    change_events: list[GraphChangeEvent]
    total_nodes: int
    generated_at: str
    cached: bool = False


class GraphInvestigationResponse(BaseModel):
    answer: str
    focal_node_ids: list[str] = Field(default_factory=list)
    focal_edge_ids: list[str] = Field(default_factory=list)
    change_events: list[GraphChangeEvent] = Field(default_factory=list)
    evidence_path: list[GraphEvidencePathStep] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)


class GraphBuildOptions(BaseModel):
    limit: int = 18
    confidence_min: float = 0.55
    node_kind: Literal["all", "entity", "topic"] = "all"
    window_days: int | None = 90
    # Contradiction band: [min, max] cosine between two units to qualify as contradictory.
    # min=0.55 — must be about the same topic (not orthogonal noise).
    # max=0.96 — must not be near-identical phrasing (dedup threshold is 0.97).
    # Contradictory claims are semantically close (same subject) → upper bound must be
    # close to 1.0, NOT 0.88. "Lead architect" vs "never wrote code" score ~0.89–0.93.
    contradiction_cosine_min: float = 0.55
    contradiction_cosine_max: float = 0.96
    contradiction_confidence_penalty: float = 0.6
    now: datetime = Field(default_factory=lambda: datetime.now(UTC))


class _GroupSummary(BaseModel):
    key: str
    kind: NodeKind
    title: str
    units: list[GraphEvidenceUnit]


class _EdgeAccumulator(BaseModel):
    source_id: str
    target_id: str
    relation_type: str
    evidence_ids: set[str] = Field(default_factory=set)


def _slugify(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return clean or hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def make_node_id(kind: NodeKind, title: str) -> str:
    return f"{kind}:{_slugify(title)}"


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", text.lower())).strip()


def _token_set(text: str) -> set[str]:
    return {token for token in _normalize_text(text).split() if token and token not in _STOPWORDS}


def _jaccard_similarity(left: str, right: str) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens and not right_tokens:
        return 1.0
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


def _shorten(text: str, limit: int = 180) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _format_display_timestamp(timestamp: datetime | None) -> str | None:
    if timestamp is None:
        return None
    return timestamp.isoformat()


def _format_node_subtitle(kind: NodeKind, evidence_count: int, timestamp: datetime | None) -> str:
    kind_label = "Entity" if kind == "entity" else "Topic"
    evidence_label = "evidence" if evidence_count == 1 else "evidence items"
    if timestamp is None:
        return f"{kind_label} • {evidence_count} {evidence_label}"
    return f"{kind_label} • {evidence_count} {evidence_label} • updated {timestamp.strftime('%b %d')}"


def _status_reason_for_node(status: NodeStatus, title: str, events: list[GraphChangeEvent]) -> str:
    if status == "contradictory":
        return f"Conflicting evidence is active for {title}."
    if status == "changed":
        return f"Recent evidence suggests {title} changed."
    if status == "stale":
        return f"{title} has not been refreshed while connected signals moved."
    if events:
        return events[0].summary
    return f"{title} is currently supported by consistent evidence."


def _format_time_window(start: datetime | None, end: datetime | None) -> str | None:
    if start and end:
        return f"{start.date().isoformat()} to {end.date().isoformat()}"
    if end:
        return end.date().isoformat()
    if start:
        return start.date().isoformat()
    return None


def _recency_score(timestamp: datetime | None, now: datetime) -> float:
    if timestamp is None:
        return 0.2
    age_days = max((now - timestamp).total_seconds() / 86400, 0.0)
    return 1.0 / (1.0 + (age_days / 30.0))


def _confidence_for_units(units: list[GraphEvidenceUnit], now: datetime) -> float:
    evidence_component = min(0.35, 0.15 * math.log1p(len(units)))
    proof_component = min(0.15, 0.04 * math.log1p(sum(max(unit.proof_count, 0) for unit in units)))
    access_component = min(0.15, 0.04 * math.log1p(sum(max(unit.access_count, 0) for unit in units)))
    latest_timestamp = max((unit.effective_timestamp() for unit in units), default=None)
    recency_component = 0.25 * _recency_score(latest_timestamp, now)
    return round(_clamp(0.2 + evidence_component + proof_component + access_component + recency_component), 3)


def _contradiction_severity(events: list[GraphChangeEvent]) -> float:
    return max((event.confidence for event in events if event.change_type == "contradiction"), default=0.0)


def _surface_confidence(base_confidence: float, events: list[GraphChangeEvent], penalty_weight: float) -> float:
    severity = _contradiction_severity(events)
    if severity <= 0.0:
        return base_confidence
    return round(_clamp(base_confidence * (1.0 - severity * penalty_weight)), 3)


def _importance_for_units(units: list[GraphEvidenceUnit], centrality: float) -> float:
    evidence_component = min(1.0, math.log1p(len(units)) / 2.5)
    support_component = min(
        1.0, math.log1p(sum(max(unit.proof_count, 0) + max(unit.access_count, 0) for unit in units)) / 3.0
    )
    return round(_clamp(0.4 * centrality + 0.35 * evidence_component + 0.25 * support_component), 3)


# Cosine threshold above which two units are considered the same semantic state
# (paraphrase / re-statement of same fact — not a genuine state transition).
_SEMANTIC_DEDUP_COSINE_THRESHOLD = 0.97


def _sorted_distinct_units(units: list[GraphEvidenceUnit]) -> list[GraphEvidenceUnit]:
    """Return units sorted by effective_timestamp, deduplicating semantically equivalent ones.

    Two units are considered duplicates when:
      1. Their embeddings have cosine similarity >= _SEMANTIC_DEDUP_COSINE_THRESHOLD  (semantic)
      OR
      2. Their normalised texts are identical  (exact, kept as fast-path fallback)

    The *earlier* unit in a duplicate pair is kept so that the temporal chain
    reflects the first time a state was introduced, not a later paraphrase of it.
    """
    ordered = sorted(
        units,
        key=lambda unit: (unit.effective_timestamp() or datetime.min.replace(tzinfo=UTC), unit.id),
    )
    distinct: list[GraphEvidenceUnit] = []
    seen_texts: set[str] = set()

    for unit in ordered:
        # Fast-path: exact normalized text match
        normalized = _normalize_text(unit.text)
        if normalized in seen_texts:
            continue

        # Semantic dedup via cosine — only when embeddings available
        if unit.embedding is not None:
            is_dup = False
            for kept in distinct:
                if kept.embedding is None:
                    continue
                sim = cosine_similarity(unit.embedding, kept.embedding)
                if sim is not None and sim >= _SEMANTIC_DEDUP_COSINE_THRESHOLD:
                    is_dup = True
                    break
            if is_dup:
                continue

        seen_texts.add(normalized)
        distinct.append(unit)

    return distinct


def _leading_entity(unit: GraphEvidenceUnit) -> str | None:
    """Return the entity that appears earliest (leftmost) in the unit's text.

    Used for contradiction ownership: a contradiction pair fires on entity X only if
    X is the leading entity in BOTH units.  This prevents project nodes (e.g. 'atulya')
    from claiming contradictions that are really about a person ('anurag') who happens
    to be mentioned in the same sentences.

    Algorithm: for each entity in unit.entities, find the first index where
    a case-insensitive word-boundary match occurs. Return the entity with the
    lowest index.  Returns None if no entities are present.
    """
    if not unit.entities:
        return None
    best_entity: str | None = None
    best_pos: int | None = None
    for entity in unit.entities:
        match = re.search(rf"\b{re.escape(entity)}\b", unit.text, flags=re.IGNORECASE)
        if match is None:
            continue
        pos = match.start()
        if best_pos is None or pos < best_pos:
            best_pos = pos
            best_entity = entity.lower()
    return best_entity


def _event_id(
    summary: _GroupSummary,
    change_type: ChangeType,
    *evidence_ids: str,
) -> str:
    suffix = ":".join(evidence_ids) if evidence_ids else "none"
    return f"event:{summary.kind}:{_slugify(summary.title)}:{change_type}:{suffix}"


def _is_contradictory(
    left: GraphEvidenceUnit,
    right: GraphEvidenceUnit,
    *,
    contradiction_cosine_min: float,
    contradiction_cosine_max: float,
) -> bool:
    left_tokens = _token_set(left.text)
    right_tokens = _token_set(right.text)
    overlap = left_tokens & right_tokens
    if len(overlap) < 2:
        return False
    left_negated = bool(left_tokens & _NEGATION_MARKERS)
    right_negated = bool(right_tokens & _NEGATION_MARKERS)
    if left_negated == right_negated:
        return False

    similarity = cosine_similarity(left.embedding, right.embedding)
    if similarity is None:
        return False
    return contradiction_cosine_min <= similarity <= contradiction_cosine_max


def _build_change_events(
    summary: _GroupSummary,
    confidence: float,
    options: GraphBuildOptions,
) -> list[GraphChangeEvent]:
    """Detect change and contradiction events for a node's evidence."""
    if summary.kind == "topic":
        return []

    distinct_units = _sorted_distinct_units(summary.units)
    if len(distinct_units) < 2:
        return []

    events: list[GraphChangeEvent] = []
    for previous, current in zip(distinct_units[:-1], distinct_units[1:]):
        previous_ts = previous.effective_timestamp()
        current_ts = current.effective_timestamp()
        if previous_ts is None or current_ts is None or current_ts <= previous_ts:
            continue

        similarity = _jaccard_similarity(previous.text, current.text)
        if similarity >= 0.55:
            continue

        if summary.kind == "entity":
            node_slug = _slugify(summary.title)
            prev_lead = _leading_entity(previous)
            curr_lead = _leading_entity(current)
            if prev_lead != node_slug and curr_lead != node_slug:
                continue

        event_confidence = round(_clamp(confidence * (1.0 - similarity * 0.45)), 3)
        events.append(
            GraphChangeEvent(
                id=_event_id(summary, "change", previous.id, current.id),
                node_id=make_node_id(summary.kind, summary.title),
                change_type="change",
                before_state=_shorten(previous.text),
                after_state=_shorten(current.text),
                confidence=event_confidence,
                time_window=_format_time_window(previous_ts, current_ts),
                evidence_ids=[previous.id, current.id],
                summary=(
                    f"{summary.title} appears to have changed from "
                    f"'{_shorten(previous.text, 70)}' to '{_shorten(current.text, 70)}'."
                ),
            )
        )

    for i, left in enumerate(distinct_units):
        left_doc = left.doc_key()
        for right in distinct_units[i + 1 :]:
            node_slug = _slugify(summary.title)
            left_lead = _leading_entity(left)
            right_lead = _leading_entity(right)
            both_led_by_node = left_lead == node_slug and right_lead == node_slug
            either_led_by_node = left_lead == node_slug or right_lead == node_slug

            same_doc = bool(left_doc and left_doc == right.doc_key())
            if same_doc and not both_led_by_node:
                continue
            if not same_doc and not either_led_by_node:
                continue
            if _is_contradictory(
                left,
                right,
                contradiction_cosine_min=options.contradiction_cosine_min,
                contradiction_cosine_max=options.contradiction_cosine_max,
            ):
                left_ts = left.effective_timestamp()
                right_ts = right.effective_timestamp()
                event_confidence = round(_clamp(confidence * 0.9), 3)
                events.append(
                    GraphChangeEvent(
                        id=_event_id(summary, "contradiction", left.id, right.id),
                        node_id=make_node_id(summary.kind, summary.title),
                        change_type="contradiction",
                        before_state=_shorten(left.text),
                        after_state=_shorten(right.text),
                        confidence=event_confidence,
                        time_window=_format_time_window(left_ts, right_ts),
                        evidence_ids=[left.id, right.id],
                        summary=f"Conflicting evidence for {summary.title}.",
                    )
                )

    return events


def _build_group_summaries(units: list[GraphEvidenceUnit], options: GraphBuildOptions) -> list[_GroupSummary]:
    entity_groups: dict[str, list[GraphEvidenceUnit]] = defaultdict(list)
    topic_groups: dict[str, list[GraphEvidenceUnit]] = defaultdict(list)

    for unit in units:
        for entity in unit.entities:
            entity_groups[entity].append(unit)
        for tag in unit.tags:
            topic_groups[tag].append(unit)

    groups: list[_GroupSummary] = []
    if options.node_kind in ("all", "entity"):
        for entity, entity_units in entity_groups.items():
            groups.append(_GroupSummary(key=entity, kind="entity", title=entity, units=entity_units))
    if options.node_kind in ("all", "topic"):
        for tag, tag_units in topic_groups.items():
            if len(tag_units) < 2:
                continue
            groups.append(_GroupSummary(key=tag, kind="topic", title=f"#{tag}", units=tag_units))

    return groups


def build_graph_intelligence(units: list[GraphEvidenceUnit], options: GraphBuildOptions) -> GraphIntelligenceResponse:
    groups = _build_group_summaries(units, options)
    if not groups:
        return GraphIntelligenceResponse(
            nodes=[],
            edges=[],
            change_events=[],
            total_nodes=0,
            generated_at=options.now.isoformat(),
            cached=False,
        )

    raw_nodes: list[GraphStateNode] = []
    group_index: dict[str, _GroupSummary] = {}
    event_map: dict[str, list[GraphChangeEvent]] = defaultdict(list)

    for summary in groups:
        confidence = _confidence_for_units(summary.units, options.now)
        if confidence < options.confidence_min:
            continue

        events = _build_change_events(summary, confidence, options)

        # current_state follows the most recent supported unit.
        def _unit_recency_key(unit: GraphEvidenceUnit) -> tuple:
            ts = unit.effective_timestamp() or datetime.min.replace(tzinfo=UTC)
            return (ts, unit.proof_count)

        latest_unit = max(summary.units, key=_unit_recency_key)
        status: NodeStatus = "stable"
        if any(event.change_type == "contradiction" for event in events):
            status = "contradictory"
        elif any(event.change_type == "change" for event in events):
            status = "changed"

        node = GraphStateNode(
            id=make_node_id(summary.kind, summary.title),
            title=summary.title,
            kind=summary.kind,
            subtitle=_format_node_subtitle(summary.kind, len(summary.units), latest_unit.effective_timestamp()),
            current_state=_shorten(latest_unit.text),
            status=status,
            status_reason=_status_reason_for_node(status, summary.title, events),
            confidence=confidence,
            change_score=0.0,
            last_changed_at=(latest_unit.effective_timestamp() or options.now).isoformat(),
            primary_timestamp=_format_display_timestamp(latest_unit.effective_timestamp()),
            evidence_count=len(summary.units),
            tags=sorted({tag for unit in summary.units for tag in unit.tags}),
            evidence_ids=[unit.id for unit in sorted(summary.units, key=lambda item: item.id)],
        )
        raw_nodes.append(node)
        group_index[node.id] = summary
        event_map[node.id] = events

    if not raw_nodes:
        return GraphIntelligenceResponse(
            nodes=[],
            edges=[],
            change_events=[],
            total_nodes=0,
            generated_at=options.now.isoformat(),
            cached=False,
        )

    # Build deterministic relation edges from entity co-occurrence and entity-topic links.
    edges_by_key: dict[tuple[str, str, str], _EdgeAccumulator] = {}
    included_node_ids = {node.id for node in raw_nodes}

    if options.node_kind in ("all", "entity"):
        for unit in units:
            entity_titles = sorted(set(unit.entities))
            for left, right in combinations(entity_titles, 2):
                source_id = make_node_id("entity", left)
                target_id = make_node_id("entity", right)
                if source_id not in included_node_ids or target_id not in included_node_ids:
                    continue
                key = tuple(sorted((source_id, target_id)) + ["co_occurs"])
                accumulator = edges_by_key.setdefault(
                    key,
                    _EdgeAccumulator(
                        source_id=min(source_id, target_id),
                        target_id=max(source_id, target_id),
                        relation_type="co_occurs",
                    ),
                )
                accumulator.evidence_ids.add(unit.id)

    if options.node_kind in ("all", "topic"):
        for unit in units:
            for entity in set(unit.entities):
                entity_id = make_node_id("entity", entity)
                if entity_id not in included_node_ids:
                    continue
                for tag in set(unit.tags):
                    topic_id = make_node_id("topic", f"#{tag}")
                    if topic_id not in included_node_ids:
                        continue
                    key = (entity_id, topic_id, "tagged_with")
                    accumulator = edges_by_key.setdefault(
                        key,
                        _EdgeAccumulator(
                            source_id=entity_id,
                            target_id=topic_id,
                            relation_type="tagged_with",
                        ),
                    )
                    accumulator.evidence_ids.add(unit.id)

    centrality_counts: dict[str, int] = defaultdict(int)
    all_edges: list[GraphRelationEdge] = []
    for accumulator in edges_by_key.values():
        evidence_count = len(accumulator.evidence_ids)
        if evidence_count == 0:
            continue
        centrality_counts[accumulator.source_id] += evidence_count
        centrality_counts[accumulator.target_id] += evidence_count
        all_edges.append(
            GraphRelationEdge(
                id=f"edge:{accumulator.relation_type}:{_slugify(accumulator.source_id)}:{_slugify(accumulator.target_id)}",
                source_id=accumulator.source_id,
                target_id=accumulator.target_id,
                relation_type=accumulator.relation_type,
                strength=round(_clamp(math.log1p(evidence_count) / 2.0), 3),
                evidence_count=evidence_count,
            )
        )

    max_centrality = max(centrality_counts.values(), default=1)
    all_events: list[GraphChangeEvent] = []
    changed_neighbor_ids = {
        event.node_id
        for events in event_map.values()
        for event in events
        if event.change_type in ("change", "contradiction")
    }

    for node in raw_nodes:
        summary = group_index[node.id]
        latest_timestamp = max((unit.effective_timestamp() for unit in summary.units), default=None)
        centrality = centrality_counts.get(node.id, 0) / max_centrality if max_centrality else 0.0
        importance = _importance_for_units(summary.units, centrality)
        recency = _recency_score(latest_timestamp, options.now)
        node_events = event_map.get(node.id, [])

        if latest_timestamp:
            age_days = max((options.now - latest_timestamp).total_seconds() / 86400, 0.0)
            has_changed_neighbor = any(
                edge.source_id in changed_neighbor_ids or edge.target_id in changed_neighbor_ids
                for edge in all_edges
                if edge.source_id == node.id or edge.target_id == node.id
            )
            own_recent_change = any(
                event.change_type in ("change", "contradiction")
                and latest_timestamp
                and latest_timestamp >= (options.now - timedelta(days=45))
                for event in node_events
            )
            if age_days >= 45 and has_changed_neighbor and importance >= 0.35 and not own_recent_change:
                stale_event = GraphChangeEvent(
                    id=f"event:{node.id}:stale",
                    node_id=node.id,
                    change_type="stale",
                    before_state=node.current_state,
                    after_state=node.current_state,
                    confidence=round(_clamp(node.confidence * 0.9), 3),
                    time_window=_format_time_window(latest_timestamp, options.now),
                    evidence_ids=node.evidence_ids[:3],
                    summary=f"{node.title} looks stale relative to recent movement around it.",
                )
                node.status = "stale"
                node.status_reason = _status_reason_for_node("stale", node.title, node_events)
                node_events = [*node_events, stale_event]
                event_map[node.id] = node_events

        event_boost = 0.0
        if node_events:
            # Contradictions already reduce surface_confidence, so their event boost stays
            # below a clean change to avoid contradictory nodes dominating the ranking.
            for ev in node_events:
                if ev.change_type == "contradiction":
                    event_boost += ev.confidence * 0.15
                elif ev.change_type == "change":
                    event_boost += ev.confidence * 0.25
                else:  # stale
                    event_boost += ev.confidence * 0.1
            event_boost = _clamp(event_boost, 0.0, 0.35)
        stale_boost = 0.1 if any(event.change_type == "stale" for event in node_events) else 0.0
        surface_confidence = _surface_confidence(node.confidence, node_events, options.contradiction_confidence_penalty)
        node.change_score = round(
            _clamp(
                0.35 * surface_confidence
                + 0.25 * recency
                + 0.2 * centrality
                + 0.2 * importance
                + event_boost
                + stale_boost
            ),
            3,
        )
        if node_events:
            latest_event_ts = max(
                (
                    max(
                        (
                            next(
                                (unit.effective_timestamp() for unit in summary.units if unit.id == evidence_id),
                                latest_timestamp,
                            )
                            for evidence_id in event.evidence_ids
                        ),
                        default=latest_timestamp,
                    )
                    for event in node_events
                ),
                default=latest_timestamp,
            )
            node.last_changed_at = latest_event_ts.isoformat() if latest_event_ts else node.last_changed_at
            node.primary_timestamp = _format_display_timestamp(latest_timestamp)
            node.subtitle = _format_node_subtitle(node.kind, node.evidence_count, latest_timestamp)
            node.status_reason = _status_reason_for_node(node.status, node.title, node_events)
        all_events.extend(node_events)

    status_priority = {"contradictory": 0, "changed": 1, "stale": 2, "stable": 3}
    sorted_nodes = sorted(
        raw_nodes, key=lambda node: (-node.change_score, status_priority[node.status], node.title.lower())
    )
    limited_nodes = sorted_nodes[: options.limit]
    selected_ids = {node.id for node in limited_nodes}

    limited_edges = sorted(
        [edge for edge in all_edges if edge.source_id in selected_ids and edge.target_id in selected_ids],
        key=lambda edge: (-edge.strength, edge.relation_type, edge.id),
    )
    limited_events = sorted(
        [event for event in all_events if event.node_id in selected_ids],
        key=lambda event: (-event.confidence, event.change_type, event.id),
    )

    return GraphIntelligenceResponse(
        nodes=limited_nodes,
        edges=limited_edges,
        change_events=limited_events,
        total_nodes=len(raw_nodes),
        generated_at=options.now.isoformat(),
        cached=False,
    )


def investigate_graph(
    query: str,
    graph: GraphIntelligenceResponse,
    recall_units: list[GraphEvidenceUnit],
) -> GraphInvestigationResponse:
    query_tokens = _token_set(query)
    recall_ids = {unit.id for unit in recall_units}
    scored_nodes: list[tuple[float, GraphStateNode]] = []

    for node in graph.nodes:
        title_tokens = _token_set(node.title)
        state_tokens = _token_set(node.current_state)
        overlap = len((title_tokens | state_tokens) & query_tokens)
        recall_overlap = len(set(node.evidence_ids) & recall_ids)
        score = node.change_score + overlap * 0.25 + recall_overlap * 0.15
        if overlap or recall_overlap:
            scored_nodes.append((score, node))

    if not scored_nodes:
        scored_nodes = [(node.change_score, node) for node in graph.nodes[:3]]

    focal_nodes = [node for _, node in sorted(scored_nodes, key=lambda item: (-item[0], item[1].title.lower()))[:4]]
    focal_node_ids = [node.id for node in focal_nodes]
    focal_edges = [edge for edge in graph.edges if edge.source_id in focal_node_ids or edge.target_id in focal_node_ids]
    focal_edge_ids = [edge.id for edge in focal_edges[:8]]
    focal_events = [event for event in graph.change_events if event.node_id in focal_node_ids][:5]

    if focal_events:
        top_lines = [event.summary for event in focal_events[:3]]
        answer = " ".join(top_lines)
    elif focal_nodes:
        state_lines = [f"{node.title}: {node.current_state}" for node in focal_nodes[:3]]
        answer = "No high-confidence graph changes were detected for this query. " + " ".join(state_lines)
    else:
        answer = "No meaningful graph intelligence signals were found for this query."

    evidence_path: list[GraphEvidencePathStep] = []
    for node in focal_nodes[:3]:
        evidence_path.append(GraphEvidencePathStep(kind="node", id=node.id, label=node.title))
        for event in [event for event in focal_events if event.node_id == node.id][:1]:
            evidence_path.append(
                GraphEvidencePathStep(
                    kind="event",
                    id=event.id,
                    label=event.summary,
                    timestamp=event.time_window,
                )
            )
            for evidence_id in event.evidence_ids[:2]:
                evidence_unit = next((unit for unit in recall_units if unit.id == evidence_id), None)
                evidence_path.append(
                    GraphEvidencePathStep(
                        kind="memory",
                        id=evidence_id,
                        label=_shorten(evidence_unit.text if evidence_unit else evidence_id, 90),
                        timestamp=(
                            evidence_unit.effective_timestamp().isoformat()
                            if evidence_unit and evidence_unit.effective_timestamp()
                            else None
                        ),
                    )
                )

    recommended_checks: list[str] = []
    if any(event.change_type == "contradiction" for event in focal_events):
        recommended_checks.append("Review conflicting evidence and confirm which source is current.")
    if any(event.change_type == "change" for event in focal_events):
        recommended_checks.append(
            "Check downstream summaries, observations, and docs that depend on the changed state."
        )
    if any(event.change_type == "stale" for event in focal_events):
        recommended_checks.append("Refresh this area with newer evidence before acting on it.")
    if not recommended_checks:
        recommended_checks.append("Inspect the supporting evidence before promoting this state into a durable model.")

    return GraphInvestigationResponse(
        answer=answer,
        focal_node_ids=focal_node_ids,
        focal_edge_ids=focal_edge_ids,
        change_events=focal_events,
        evidence_path=evidence_path,
        recommended_checks=recommended_checks,
    )
