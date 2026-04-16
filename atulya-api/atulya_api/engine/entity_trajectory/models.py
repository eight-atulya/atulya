"""Pydantic models for entity trajectory LLM I/O and API payloads."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TrajectoryObservation(BaseModel):
    """One memory unit linked to an entity, ordered for HMM observations."""

    unit_id: str
    fact_text: str
    fact_type: str
    occurred_sort_at: datetime
    embedding: list[float]


class LLMTrajectoryLabelResponse(BaseModel):
    """Structured LLM output: vocabulary + one label per observation (same order)."""

    state_vocabulary: list[str] = Field(default_factory=list, max_length=16)
    labels: list[str] = Field(default_factory=list)


class TrajectoryViterbiStep(BaseModel):
    unit_id: str
    state: str
    occurred_sort_at: datetime
    fact_preview: str = Field(max_length=500)


class EntityTrajectoryAPIPayload(BaseModel):
    """Stable GET response shape for control plane."""

    entity_id: str
    bank_id: str
    computed_at: datetime
    state_vocabulary: list[str]
    transition_matrix: list[list[float]]
    current_state: str
    viterbi_path: list[TrajectoryViterbiStep]
    forecast_horizon: int
    forecast_distribution: dict[str, float]
    forward_log_prob: float | None
    anomaly_score: float | None
    llm_model: str
    prompt_version: str
    vocabulary_hash: str
