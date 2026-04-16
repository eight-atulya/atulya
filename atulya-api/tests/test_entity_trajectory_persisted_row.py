"""Tests for JSONB-safe deserialization of entity_trajectories rows."""

import json
from datetime import UTC, datetime
from uuid import UUID

from atulya_api.engine.entity_trajectory.persisted_row import (
    entity_trajectory_payload_from_record,
    normalize_forecast_distribution,
    normalize_transition_matrix,
)


def test_normalize_transition_matrix_from_json_string():
    raw = json.dumps([[0.5, 0.5], [0.2, 0.8]])
    m = normalize_transition_matrix(raw)
    assert m == [[0.5, 0.5], [0.2, 0.8]]


def test_normalize_transition_matrix_from_list():
    assert normalize_transition_matrix([[1, 0], [0, 1]]) == [[1.0, 0.0], [0.0, 1.0]]


def test_normalize_transition_matrix_rejects_character_iteration_bug():
    """Guarding against list(str) / iterating JSON text as char list."""
    raw = "[[0.1,0.9],[0.4,0.6]]"
    # Must not treat as iterable of chars
    m = normalize_transition_matrix(raw)
    assert len(m) == 2
    assert len(m[0]) == 2


def test_normalize_forecast_distribution_string():
    raw = json.dumps({"A": 0.25, "B": 0.75})
    d = normalize_forecast_distribution(raw)
    assert d == {"A": 0.25, "B": 0.75}


def test_entity_trajectory_payload_full_record():
    eid = UUID("058eb16f-98ac-435d-8312-44d1e89c2bbc")
    row = {
        "entity_id": eid,
        "bank_id": "my-org",
        "computed_at": datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
        "state_vocabulary": json.dumps(["S0", "S1"]),
        "vocabulary_hash": "abc",
        "transition_matrix": json.dumps([[0.4, 0.6], [0.3, 0.7]]),
        "current_state": "S1",
        "viterbi_path": json.dumps(
            [
                {
                    "unit_id": "u1",
                    "state": "S0",
                    "occurred_sort_at": "2026-04-15T12:00:00+00:00",
                    "fact_preview": "x",
                }
            ]
        ),
        "forecast_horizon": 5,
        "forecast_distribution": json.dumps({"S0": 0.1, "S1": 0.9}),
        "forward_log_prob": -2.5,
        "anomaly_score": 0.3,
        "llm_model": "lmstudio/x",
        "prompt_version": "v1",
    }
    out = entity_trajectory_payload_from_record(row)
    assert out["entity_id"] == str(eid)
    assert out["state_vocabulary"] == ["S0", "S1"]
    assert out["transition_matrix"] == [[0.4, 0.6], [0.3, 0.7]]
    assert len(out["viterbi_path"]) == 1
    assert out["forecast_distribution"] == {"S0": 0.1, "S1": 0.9}
    assert out["forward_log_prob"] == -2.5
