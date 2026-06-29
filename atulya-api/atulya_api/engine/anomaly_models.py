"""
Typed models for anomaly intelligence.

Purpose
    Shared vocabulary for write-time and post-retain anomaly detection,
    persistence in ``anomaly_events``, and adaptive correction audit rows.

Trigger path
    - ``engine/retain/orchestrator.py`` calls flaw detection and anomaly
      detection during retain; results persist via ``anomaly_detection``.
    - ``adaptive_correction.apply_adaptive_corrections`` reads persisted events.
    - API routes expose summaries built from these types.

Inputs
    - Detector modules populate ``DetectedAnomaly`` before persistence.
    - DB rows hydrate ``PersistedAnomaly`` / ``PersistedCorrection``.

Outputs
  - Structured anomalies for logging, API, and in-transaction corrections.

Side effects
    None at model layer.

Mutability
    ``DetectedAnomaly`` is ephemeral; persisted rows track status transitions:
    ``open`` → ``acknowledged`` | ``resolved`` | ``suppressed``.

Impact radius
    - Retain pipeline integrity, confidence_score adjustments, operator dashboards.

Core logic
    - ``AnomalyType`` spans contradictions, temporal/entity issues, causal flaws,
      and pattern violations.
    - ``severity`` is 0.0–1.0; drives auto-correction thresholds.

Failure modes
    - Pydantic bounds on severity fields.

Maintenance notes
    - Good: add new ``AnomalyType`` with matching detection + correction path.
    - Bad: reuse severity scale for unrelated semantics without updating docs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AnomalyType = Literal[
    "contradiction",
    "temporal_inconsistency",
    "entity_inconsistency",
    "flaw_circular",
    "flaw_temporal_violation",
    "flaw_missing_step",
    "flaw_unsupported_opinion",
    "pattern_anti_pattern",
    "pattern_violation",
]

AnomalyStatus = Literal["open", "acknowledged", "resolved", "suppressed"]
CorrectionType = Literal[
    "confidence_adjustment",
    "belief_revision",
    "chain_repair_suggestion",
    "pattern_evolution",
    "suppression",
]


class DetectedAnomaly(BaseModel):
    """In-memory anomaly before persistence; produced by detector modules."""

    anomaly_type: AnomalyType
    severity: float = Field(ge=0.0, le=1.0)
    unit_ids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    description: str
    metadata: dict[str, object] = Field(default_factory=dict)


class PersistedAnomaly(BaseModel):
    """Row-shaped anomaly after insert into ``anomaly_events``."""

    id: str
    bank_id: str
    anomaly_type: AnomalyType
    severity: float = Field(ge=0.0, le=1.0)
    status: AnomalyStatus
    unit_ids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    description: str
    metadata: dict[str, object] = Field(default_factory=dict)
    detected_at: datetime
    resolved_at: datetime | None = None
    resolved_by: str | None = None


class PersistedCorrection(BaseModel):
    """Audit record for an automatic or manual correction tied to an anomaly."""

    id: str
    bank_id: str
    anomaly_id: str
    correction_type: CorrectionType
    target_unit_id: str | None = None
    before_state: dict[str, object] = Field(default_factory=dict)
    after_state: dict[str, object] = Field(default_factory=dict)
    confidence_delta: float | None = None
    applied_at: datetime
    applied_by: str


class AnomalyIntelligenceSummary(BaseModel):
    """Aggregated anomaly stats for bank-level intelligence endpoints."""

    total_events: int
    open_events: int
    resolved_events: int
    avg_severity: float = Field(ge=0.0, le=1.0)
    by_type: dict[str, int] = Field(default_factory=dict)
