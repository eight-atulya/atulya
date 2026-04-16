"""
Integration-style tests for entity trajectory: real DB rows + mocked LLM.

Mirrors patterns from test_reflect_agent (mock_llm.call → AsyncMock with TokenUsage)
and test_anomaly_detection / test_graph_intelligence (seed memory_units + entities + unit_entities).

Optional **local LLM** smoke test (slow): set ``ATULYA_API_ENTITY_TRAJECTORY_LLM_TEST=1`` and
``ATULYA_API_LLM_PROVIDER`` to ``ollama`` or ``lmstudio`` with ``ATULYA_API_LLM_MODEL`` loaded locally.
Uses three facts (minimum). Override ``ATULYA_API_LLM_BASE_URL`` when the server is not on localhost
(e.g. Docker Desktop: ``http://host.docker.internal:11434/v1``).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from atulya_api.engine.db_utils import acquire_with_retry
from atulya_api.engine.entity_trajectory.models import LLMTrajectoryLabelResponse
from atulya_api.engine.entity_trajectory.service import EntityTrajectoryService
from atulya_api.engine.llm_wrapper import LLMProvider
from atulya_api.engine.memory_engine import fq_table
from atulya_api.engine.response_models import TokenUsage


def _embedding(a: float, b: float) -> list[float]:
    vec = [0.0] * 384
    vec[0] = a
    vec[1] = b
    return vec


def _mock_trajectory_llm(
    *,
    vocabulary: list[str],
    labels: list[str],
    provider: str = "mock",
    model: str = "trajectory-test",
) -> MagicMock:
    """LLMConfig-shaped mock: call() returns (LLMTrajectoryLabelResponse, TokenUsage)."""
    llm = MagicMock()
    llm.provider = provider
    llm.model = model
    usage = TokenUsage(input_tokens=120, output_tokens=80, total_tokens=200)
    llm.call = AsyncMock(
        return_value=(
            LLMTrajectoryLabelResponse(state_vocabulary=vocabulary, labels=labels),
            usage,
        )
    )
    return llm


def _resolved_config(*, enabled: bool = True, retain_max_completion_tokens: int = 8192) -> SimpleNamespace:
    return SimpleNamespace(
        enable_entity_trajectories=enabled,
        entity_trajectory_min_facts=3,
        entity_trajectory_max_facts_per_entity=50,
        entity_trajectory_laplace_alpha=0.1,
        entity_trajectory_forecast_horizon=5,
        entity_trajectory_prompt_version="v1",
        retain_max_completion_tokens=retain_max_completion_tokens,
    )


def _local_openai_compatible_trajectory_llm_or_skip() -> LLMProvider:
    """Real OpenAI-compatible local server (Ollama / LM Studio); skips unless opt-in env is set."""
    flag = os.getenv("ATULYA_API_ENTITY_TRAJECTORY_LLM_TEST", "").strip().lower()
    if flag not in ("1", "true", "yes"):
        pytest.skip(
            "Set ATULYA_API_ENTITY_TRAJECTORY_LLM_TEST=1 to run the local LLM entity-trajectory smoke test."
        )
    provider = os.getenv("ATULYA_API_LLM_PROVIDER", "").strip().lower()
    if provider not in ("ollama", "lmstudio"):
        pytest.skip(
            "Local trajectory LLM test expects ATULYA_API_LLM_PROVIDER=ollama or lmstudio "
            f"(got {provider!r}). Cloud APIs are not run from this test."
        )
    model = os.getenv("ATULYA_API_LLM_MODEL", "").strip()
    if not model:
        pytest.skip("Set ATULYA_API_LLM_MODEL to a model loaded in Ollama or LM Studio.")
    api_key = os.getenv("ATULYA_API_LLM_API_KEY", "") or "local"
    base_url = (os.getenv("ATULYA_API_LLM_BASE_URL") or "").strip()
    return LLMProvider(provider=provider, api_key=api_key, base_url=base_url, model=model)


@pytest.mark.asyncio
async def test_compute_and_persist_writes_entity_trajectory_with_mock_llm(memory):
    """End-to-end through service: observations from DB, fixed LLM labels, HMM + persist."""
    bank_id = f"entity_traj_int_{uuid4()}"
    base = datetime.now(UTC) - timedelta(days=10)

    labels_for_facts = [
        "DISCOVERY",
        "DISCOVERY",
        "BUILD",
        "BUILD",
        "MAINTENANCE",
    ]
    vocab = ["DISCOVERY", "BUILD", "MAINTENANCE"]
    mock_llm = _mock_trajectory_llm(vocabulary=vocab, labels=labels_for_facts)

    pool = await memory._get_pool()
    async with acquire_with_retry(pool) as conn:
        entity_id = await conn.fetchval(
            f"""
            INSERT INTO {fq_table("entities")} (bank_id, canonical_name, first_seen, last_seen, mention_count)
            VALUES ($1, $2, $3, $4, 5)
            RETURNING id::text
            """,
            bank_id,
            "Project Alpha",
            base,
            datetime.now(UTC),
        )

        texts = [
            "Team scoped the problem and picked a design.",
            "Stakeholders agreed on milestones.",
            "Implementation started on the core service.",
            "Integration tests passed in staging.",
            "Service is in steady operations with on-call rotation.",
        ]
        for i, text in enumerate(texts):
            ts = base + timedelta(days=i)
            uid = await conn.fetchval(
                f"""
                INSERT INTO {fq_table("memory_units")}
                (bank_id, text, embedding, fact_type, created_at, occurred_start, mentioned_at, proof_count)
                VALUES ($1, $2, $3::vector, 'world', $4, $4, $4, 2)
                RETURNING id::text
                """,
                bank_id,
                text,
                str(_embedding(1.0 - i * 0.05, 0.1 + i * 0.02)),
                ts,
            )
            await conn.execute(
                f"INSERT INTO {fq_table('unit_entities')} (unit_id, entity_id) VALUES ($1::uuid, $2::uuid)",
                uid,
                entity_id,
            )

        ok = await EntityTrajectoryService.compute_and_persist(
            conn,
            bank_id=bank_id,
            entity_id=str(entity_id),
            entity_canonical_name="Project Alpha",
            llm_config=mock_llm,
            resolved_config=_resolved_config(),
        )
        assert ok is True

        row = await conn.fetchrow(
            f"""
            SELECT state_vocabulary, current_state, viterbi_path, transition_matrix,
                   forecast_distribution, forward_log_prob, anomaly_score, llm_model, prompt_version
            FROM {fq_table("entity_trajectories")}
            WHERE bank_id = $1 AND entity_id = $2::uuid
            """,
            bank_id,
            entity_id,
        )

    assert row is not None
    sv = row["state_vocabulary"]
    if isinstance(sv, str):
        sv = json.loads(sv)
    assert set(sv) >= {"DISCOVERY", "BUILD", "MAINTENANCE"}

    path = row["viterbi_path"]
    if isinstance(path, str):
        path = json.loads(path)
    assert len(path) == len(texts)

    assert row["current_state"] in sv
    assert row["llm_model"].startswith("mock/")
    assert row["prompt_version"] == "v1"

    fd = row["forecast_distribution"]
    if isinstance(fd, str):
        fd = json.loads(fd)
    assert abs(sum(fd.values()) - 1.0) < 1e-6

    assert row["forward_log_prob"] is not None
    assert float(row["forward_log_prob"]) < 0.0

    assert 0.0 <= float(row["anomaly_score"]) <= 1.0

    tm = row["transition_matrix"]
    if isinstance(tm, str):
        tm = json.loads(tm)
    assert len(tm) == len(sv)
    for r in tm:
        assert abs(sum(r) - 1.0) < 1e-6

    mock_llm.call.assert_awaited_once()


@pytest.mark.asyncio
async def test_compute_and_persist_returns_false_when_disabled(memory):
    bank_id = f"entity_traj_off_{uuid4()}"
    mock_llm = _mock_trajectory_llm(vocabulary=["A", "B"], labels=["A", "A", "B"])

    pool = await memory._get_pool()
    async with acquire_with_retry(pool) as conn:
        entity_id = await conn.fetchval(
            f"""
            INSERT INTO {fq_table("entities")} (bank_id, canonical_name, first_seen, last_seen, mention_count)
            VALUES ($1, $2, $3, $4, 3)
            RETURNING id::text
            """,
            bank_id,
            "Unused",
            datetime.now(UTC),
            datetime.now(UTC),
        )
        for i in range(3):
            ts = datetime.now(UTC) - timedelta(days=3 - i)
            uid = await conn.fetchval(
                f"""
                INSERT INTO {fq_table("memory_units")}
                (bank_id, text, embedding, fact_type, created_at, occurred_start, mentioned_at, proof_count)
                VALUES ($1, $2, $3::vector, 'world', $4, $4, $4, 1)
                RETURNING id::text
                """,
                bank_id,
                f"fact {i}",
                str(_embedding(0.9, 0.1)),
                ts,
            )
            await conn.execute(
                f"INSERT INTO {fq_table('unit_entities')} (unit_id, entity_id) VALUES ($1::uuid, $2::uuid)",
                uid,
                entity_id,
            )

        ok = await EntityTrajectoryService.compute_and_persist(
            conn,
            bank_id=bank_id,
            entity_id=str(entity_id),
            entity_canonical_name="Unused",
            llm_config=mock_llm,
            resolved_config=_resolved_config(enabled=False),
        )
        assert ok is False

    mock_llm.call.assert_not_called()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.timeout(180)
@pytest.mark.asyncio
async def test_compute_and_persist_with_local_llm_opt_in(memory):
    """
    One structured-output call to local Ollama/LM Studio; three facts (min threshold).

    Opt-in only: keeps default pytest runs fast and offline. Excludes remote paid APIs.
    """
    llm = _local_openai_compatible_trajectory_llm_or_skip()
    bank_id = f"entity_traj_llm_{uuid4()}"
    base = datetime.now(UTC) - timedelta(days=5)
    texts = [
        "Acme Corp announced a new product line.",
        "Engineering shipped the MVP to beta customers.",
        "Operations took over on-call for the service.",
    ]

    pool = await memory._get_pool()
    async with acquire_with_retry(pool) as conn:
        entity_id = await conn.fetchval(
            f"""
            INSERT INTO {fq_table("entities")} (bank_id, canonical_name, first_seen, last_seen, mention_count)
            VALUES ($1, $2, $3, $4, 3)
            RETURNING id::text
            """,
            bank_id,
            "Acme Corp",
            base,
            datetime.now(UTC),
        )
        for i, text in enumerate(texts):
            ts = base + timedelta(days=i)
            uid = await conn.fetchval(
                f"""
                INSERT INTO {fq_table("memory_units")}
                (bank_id, text, embedding, fact_type, created_at, occurred_start, mentioned_at, proof_count)
                VALUES ($1, $2, $3::vector, 'world', $4, $4, $4, 1)
                RETURNING id::text
                """,
                bank_id,
                text,
                str(_embedding(0.95 - i * 0.1, 0.1 + i * 0.05)),
                ts,
            )
            await conn.execute(
                f"INSERT INTO {fq_table('unit_entities')} (unit_id, entity_id) VALUES ($1::uuid, $2::uuid)",
                uid,
                entity_id,
            )

        ok = await EntityTrajectoryService.compute_and_persist(
            conn,
            bank_id=bank_id,
            entity_id=str(entity_id),
            entity_canonical_name="Acme Corp",
            llm_config=llm,
            resolved_config=_resolved_config(retain_max_completion_tokens=512),
        )
        assert ok is True

        row = await conn.fetchrow(
            f"""
            SELECT state_vocabulary, viterbi_path, forward_log_prob, llm_model
            FROM {fq_table("entity_trajectories")}
            WHERE bank_id = $1 AND entity_id = $2::uuid
            """,
            bank_id,
            entity_id,
        )

    assert row is not None
    sv = row["state_vocabulary"]
    if isinstance(sv, str):
        sv = json.loads(sv)
    assert 2 <= len(sv) <= 16

    path = row["viterbi_path"]
    if isinstance(path, str):
        path = json.loads(path)
    assert len(path) == 3

    assert row["forward_log_prob"] is not None
    assert float(row["forward_log_prob"]) < 0.0

    model_label = str(row["llm_model"] or "")
    assert llm.provider in model_label
