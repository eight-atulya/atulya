"""
Shared temporal normalization for timeline-aware memory rendering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

TimelineAnchorKind = Literal[
    "event_exact",
    "event_inferred",
    "ongoing_state",
    "future_plan",
    "recorded_only",
    "derived_snapshot",
]

TemporalDirection = Literal["past", "present", "future", "atemporal"]

TEMPORAL_INFERENCE_CONFIDENCE_THRESHOLD = 0.7

_FUTURE_MARKERS = (
    "will ",
    "going to ",
    "plan to ",
    "plans to ",
    "planning to ",
    "scheduled",
    "schedule ",
    "tomorrow",
    "next week",
    "next month",
    "next year",
)
_ONGOING_STATE_MARKERS = (
    " works ",
    " work at ",
    " lives ",
    " live in ",
    " prefers ",
    " prefer ",
    " likes ",
    " like ",
    " loves ",
    " love ",
    " enjoys ",
    " enjoy ",
    " knows ",
    " know ",
    " leads ",
    " lead ",
    " is ",
    " are ",
    " has ",
    " have ",
)
_PAST_MARKERS = (
    "yesterday",
    "last ",
    "ago",
    "visited",
    "went",
    "did",
    "was",
    "were",
    "had",
)
_ABSOLUTE_DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(?:,\s+\d{4})?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TimelineTemporalMetadata:
    anchor_at: datetime | None
    anchor_kind: TimelineAnchorKind
    direction: TemporalDirection
    confidence: float | None
    reference_text: str | None


def normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def infer_direction(anchor_at: datetime | None, recorded_at: datetime | None) -> TemporalDirection:
    normalized_anchor_at = normalize_datetime(anchor_at)
    normalized_recorded_at = normalize_datetime(recorded_at)
    if normalized_anchor_at is None:
        return "atemporal"
    if normalized_recorded_at is None:
        return "present"
    delta_seconds = (normalized_anchor_at - normalized_recorded_at).total_seconds()
    if delta_seconds > 3600:
        return "future"
    if delta_seconds < -3600:
        return "past"
    return "present"


def default_anchor_kind(
    *,
    occurred_start: datetime | None,
    mentioned_at: datetime | None,
    created_at: datetime | None,
) -> TimelineAnchorKind:
    if occurred_start is not None:
        return "event_exact"
    if mentioned_at is not None or created_at is not None:
        return "recorded_only"
    return "recorded_only"


def classify_fact_temporal_metadata(
    *,
    fact_text: str,
    occurred_start: datetime | None,
    mentioned_at: datetime | None,
    created_at: datetime | None = None,
    explicit_temporal: bool = False,
    inferred_temporal: bool = False,
    fact_kind: str = "conversation",
) -> TimelineTemporalMetadata:
    recorded_at = normalize_datetime(mentioned_at) or normalize_datetime(created_at)
    anchor_at = normalize_datetime(occurred_start) or recorded_at
    normalized_text = f" {fact_text.lower()} "

    if occurred_start is not None and explicit_temporal:
        direction = infer_direction(anchor_at, recorded_at)
        anchor_kind: TimelineAnchorKind = "future_plan" if direction == "future" else "event_exact"
        return TimelineTemporalMetadata(
            anchor_at=anchor_at,
            anchor_kind=anchor_kind,
            direction=direction,
            confidence=1.0,
            reference_text=extract_temporal_reference_text(fact_text),
        )

    if occurred_start is not None and inferred_temporal:
        direction = infer_direction(anchor_at, recorded_at)
        confidence = 0.72
        anchor_kind = "future_plan" if direction == "future" else "event_inferred"
        if confidence >= TEMPORAL_INFERENCE_CONFIDENCE_THRESHOLD:
            return TimelineTemporalMetadata(
                anchor_at=anchor_at,
                anchor_kind=anchor_kind,
                direction=direction,
                confidence=confidence,
                reference_text=extract_temporal_reference_text(fact_text),
            )

    if any(marker in normalized_text for marker in _FUTURE_MARKERS):
        return TimelineTemporalMetadata(
            anchor_at=recorded_at,
            anchor_kind="future_plan",
            direction="future",
            confidence=0.45,
            reference_text=extract_temporal_reference_text(fact_text),
        )

    if fact_kind == "conversation" and any(marker in normalized_text for marker in _ONGOING_STATE_MARKERS):
        return TimelineTemporalMetadata(
            anchor_at=recorded_at,
            anchor_kind="ongoing_state",
            direction="present",
            confidence=0.62,
            reference_text=extract_temporal_reference_text(fact_text),
        )

    if any(marker in normalized_text for marker in _PAST_MARKERS):
        return TimelineTemporalMetadata(
            anchor_at=recorded_at,
            anchor_kind="recorded_only",
            direction="past",
            confidence=0.4,
            reference_text=extract_temporal_reference_text(fact_text),
        )

    return TimelineTemporalMetadata(
        anchor_at=recorded_at,
        anchor_kind="recorded_only",
        direction="atemporal" if recorded_at is None else "present",
        confidence=0.35 if recorded_at is not None else None,
        reference_text=extract_temporal_reference_text(fact_text),
    )


def classify_snapshot_temporal_metadata(
    *,
    recorded_at: datetime | None,
    anchor_at: datetime | None = None,
) -> TimelineTemporalMetadata:
    normalized_recorded_at = normalize_datetime(recorded_at)
    normalized_anchor_at = normalize_datetime(anchor_at) or normalized_recorded_at
    return TimelineTemporalMetadata(
        anchor_at=normalized_anchor_at,
        anchor_kind="derived_snapshot",
        direction="present",
        confidence=1.0,
        reference_text=None,
    )


def extract_temporal_reference_text(text: str) -> str | None:
    match = _ABSOLUTE_DATE_RE.search(text)
    if match:
        return match.group(0)
    lowered = text.lower()
    for marker in _FUTURE_MARKERS + _PAST_MARKERS:
        if marker.strip() in lowered:
            return marker.strip()
    return None


def serialize_temporal_metadata(
    *,
    anchor_at: datetime | str | None,
    anchor_kind: TimelineAnchorKind | str,
    recorded_at: datetime | str | None,
    direction: TemporalDirection | str,
    confidence: float | None,
    reference_text: str | None,
) -> dict[str, object | None]:
    def _to_iso(value: datetime | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        normalized = normalize_datetime(value)
        return normalized.isoformat() if normalized else None

    return {
        "anchor_at": _to_iso(anchor_at),
        "anchor_kind": anchor_kind,
        "recorded_at": _to_iso(recorded_at),
        "direction": direction,
        "confidence": confidence,
        "reference_text": reference_text,
    }
