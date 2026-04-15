"""
Typed models for anomaly intelligence.
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
    anomaly_type: AnomalyType
    severity: float = Field(ge=0.0, le=1.0)
    unit_ids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    description: str
    metadata: dict[str, object] = Field(default_factory=dict)


class PersistedAnomaly(BaseModel):
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
    total_events: int
    open_events: int
    resolved_events: int
    avg_severity: float = Field(ge=0.0, le=1.0)
    by_type: dict[str, int] = Field(default_factory=dict)
