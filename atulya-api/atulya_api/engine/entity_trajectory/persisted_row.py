"""
Deserialize `entity_trajectories` rows from PostgreSQL into stable API shapes.

All JSONB columns pass through `decode_jsonb` first so str/list/dict from asyncpg are handled
uniformly. This is the single normalization boundary for reads (pair with INSERT in service.py).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from atulya_api.engine.jsonb_compat import decode_jsonb

logger = logging.getLogger(__name__)


def normalize_state_vocabulary(raw: Any) -> list[str]:
    data = decode_jsonb(raw, [])
    if not isinstance(data, list):
        logger.warning("entity_trajectories.state_vocabulary is not a JSON array (type=%s)", type(raw).__name__)
        return []
    return [str(x) for x in data if x is not None]


def normalize_transition_matrix(raw: Any) -> list[list[float]]:
    """Square stochastic matrix: list of rows, each row list[float]."""
    data = decode_jsonb(raw, [])
    if not isinstance(data, list):
        logger.warning("entity_trajectories.transition_matrix is not a JSON array (type=%s)", type(raw).__name__)
        return []
    out: list[list[float]] = []
    for row in data:
        if isinstance(row, (list, tuple)):
            try:
                out.append([float(x) for x in row])
            except (TypeError, ValueError) as e:
                logger.warning("entity_trajectories.transition_matrix bad row skipped: %s", e)
                continue
        else:
            logger.warning("entity_trajectories.transition_matrix row is not an array (type=%s)", type(row).__name__)
    return out


def normalize_viterbi_path(raw: Any) -> list[dict[str, Any]]:
    """List of step objects for API / Pydantic mapping."""
    data = decode_jsonb(raw, [])
    if not isinstance(data, list):
        logger.warning("entity_trajectories.viterbi_path is not a JSON array (type=%s)", type(raw).__name__)
        return []
    steps: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict):
            steps.append(item)
        else:
            logger.warning("entity_trajectories.viterbi_path step skipped (not an object)")
    return steps


def normalize_forecast_distribution(raw: Any) -> dict[str, float]:
    data = decode_jsonb(raw, {})
    if not isinstance(data, dict):
        if data not in (None, "", []):
            logger.warning(
                "entity_trajectories.forecast_distribution is not a JSON object (type=%s)", type(data).__name__
            )
        return {}
    out: dict[str, float] = {}
    for k, v in data.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def entity_trajectory_payload_from_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """
    Map a DB row (asyncpg.Record or dict) to the dict consumed by HTTP + internal callers.

    Guaranteed shapes:
    - state_vocabulary: list[str]
    - transition_matrix: list[list[float]]
    - viterbi_path: list[dict]
    - forecast_distribution: dict[str, float]
    """
    computed = row.get("computed_at")
    if isinstance(computed, datetime):
        computed_at = computed.isoformat()
    elif isinstance(computed, str):
        computed_at = computed
    else:
        computed_at = None

    entity_id = row.get("entity_id")
    if isinstance(entity_id, UUID):
        entity_id_str = str(entity_id)
    else:
        entity_id_str = str(entity_id) if entity_id is not None else ""

    flp = row.get("forward_log_prob")
    if flp is not None:
        try:
            forward_log_prob = float(flp)
        except (TypeError, ValueError):
            forward_log_prob = None
    else:
        forward_log_prob = None

    ascore = row.get("anomaly_score")
    if ascore is not None:
        try:
            anomaly_score = float(ascore)
        except (TypeError, ValueError):
            anomaly_score = None
    else:
        anomaly_score = None

    return {
        "entity_id": entity_id_str,
        "bank_id": row.get("bank_id") or "",
        "computed_at": computed_at,
        "state_vocabulary": normalize_state_vocabulary(row.get("state_vocabulary")),
        "vocabulary_hash": row.get("vocabulary_hash") or "",
        "transition_matrix": normalize_transition_matrix(row.get("transition_matrix")),
        "current_state": row.get("current_state") or "",
        "viterbi_path": normalize_viterbi_path(row.get("viterbi_path")),
        "forecast_horizon": int(row.get("forecast_horizon") or 0),
        "forecast_distribution": normalize_forecast_distribution(row.get("forecast_distribution")),
        "forward_log_prob": forward_log_prob,
        "anomaly_score": anomaly_score,
        "llm_model": row.get("llm_model") or "",
        "prompt_version": row.get("prompt_version") or "",
    }
