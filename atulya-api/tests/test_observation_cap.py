"""Unit tests for the ``max_observations_per_scope`` consolidation cap.

These tests exercise the helpers and LLM call wiring in
``atulya_api.engine.consolidation.consolidator`` without requiring a live
PostgreSQL or LLM.

Behaviours covered:

* ``_build_response_model`` returns the unconstrained model when the cap is
  ``None`` and a constrained subclass with ``Field(max_length=N)`` otherwise.
* ``_count_observations_for_scope`` short-circuits to ``0`` for empty / None
  scopes (untagged observations are exempt).
* ``_consolidate_batch_with_llm`` propagates ``remaining_slots`` into the
  prompt (capacity banner) and into the constrained response model.
* End-to-end ``_process_memory_batch`` enforces deletes-before-creates,
  drops over-cap creates even when the LLM ignores the constrained schema,
  and lets updates/deletes through unmodified at the cap.

The deeper observation_scopes integration tests (per_tag / combined /
all_combinations) live in ``tests/test_consolidation.py`` and continue to
exercise the per-pass enforcement path automatically.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from atulya_api.engine.consolidation.consolidator import (
    _BatchLLMResult,
    _ConsolidationBatchResponse,
    _CreateAction,
    _DeleteAction,
    _UpdateAction,
    _build_response_model,
    _consolidate_batch_with_llm,
    _count_observations_for_scope,
    _parse_observation_scopes,
    _process_memory_batch,
)
from atulya_api.engine.consolidation.prompts import build_batch_consolidation_prompt
from atulya_api.engine.response_models import MemoryFact


def _fake_config(**overrides: Any) -> Any:
    """Minimal stand-in for ``AtulyaConfig`` used by the consolidator."""
    defaults: dict[str, Any] = {
        "observations_mission": None,
        "consolidation_duplicate_detection_enabled": False,
        "consolidation_duplicate_cosine_threshold": 0.5,
        "consolidation_duplicate_ce_enabled": False,
        "consolidation_duplicate_ce_threshold": 0.5,
        "max_observations_per_scope": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ─── _build_response_model ────────────────────────────────────────────────────


class TestBuildResponseModel:
    def test_none_returns_unconstrained_model(self) -> None:
        assert _build_response_model(None) is _ConsolidationBatchResponse

    def test_zero_rejects_any_creates(self) -> None:
        Model = _build_response_model(0)
        # Updates and deletes still allowed
        Model(updates=[_UpdateAction(text="x", observation_id="o", source_fact_ids=["a"])])
        Model(deletes=[_DeleteAction(observation_id="o")])
        # Any non-empty creates raises validation error
        with pytest.raises(ValidationError):
            Model(creates=[_CreateAction(text="x", source_fact_ids=["a"])])

    def test_positive_allows_up_to_n_creates(self) -> None:
        Model = _build_response_model(2)
        Model(creates=[_CreateAction(text="a", source_fact_ids=["x"])])
        Model(creates=[_CreateAction(text="a", source_fact_ids=["x"]), _CreateAction(text="b", source_fact_ids=["y"])])
        with pytest.raises(ValidationError):
            Model(
                creates=[
                    _CreateAction(text="a", source_fact_ids=["x"]),
                    _CreateAction(text="b", source_fact_ids=["y"]),
                    _CreateAction(text="c", source_fact_ids=["z"]),
                ]
            )

    def test_distinct_subclass_names_per_cap(self) -> None:
        a = _build_response_model(0)
        b = _build_response_model(2)
        assert a is not b
        assert a.__name__ != b.__name__
        assert issubclass(a, _ConsolidationBatchResponse)
        assert issubclass(b, _ConsolidationBatchResponse)


# ─── _count_observations_for_scope ───────────────────────────────────────────


class TestCountObservationsForScope:
    @pytest.mark.asyncio
    async def test_untagged_scope_short_circuits_to_zero(self) -> None:
        conn = AsyncMock()
        assert await _count_observations_for_scope(conn=conn, bank_id="b", scope_tags=None) == 0
        assert await _count_observations_for_scope(conn=conn, bank_id="b", scope_tags=[]) == 0
        conn.fetchrow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tagged_scope_runs_query_and_returns_count(self) -> None:
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"n": 7})
        result = await _count_observations_for_scope(
            conn=conn, bank_id="b", scope_tags=["user:alice", "team:platform"]
        )
        assert result == 7
        conn.fetchrow.assert_awaited_once()
        # Query must use bank_id and the tag list as parameters
        args, _ = conn.fetchrow.call_args
        assert args[1] == "b"
        assert args[2] == ["user:alice", "team:platform"]


# ─── prompt capacity banner ──────────────────────────────────────────────────


class TestPromptCapacityBanner:
    def test_no_capacity_note_omits_capacity_block(self) -> None:
        prompt = build_batch_consolidation_prompt()
        assert "## CAPACITY" not in prompt

    def test_capacity_note_inserted(self) -> None:
        prompt = build_batch_consolidation_prompt(capacity_note="HARD STOP at cap.")
        assert "## CAPACITY" in prompt
        assert "HARD STOP at cap." in prompt
        # The capacity block sits before the processing rules section
        assert prompt.index("## CAPACITY") < prompt.index("Processing rules")


# ─── _consolidate_batch_with_llm ─────────────────────────────────────────────


class TestConsolidateBatchWithLLMCap:
    @pytest.mark.asyncio
    async def test_passes_unconstrained_model_when_no_cap(self) -> None:
        captured: dict[str, Any] = {}

        async def fake_call(*, messages, response_format, scope):
            captured["response_format"] = response_format
            captured["prompt"] = messages[0]["content"]
            return _ConsolidationBatchResponse()

        llm_config = SimpleNamespace(call=AsyncMock(side_effect=fake_call))

        await _consolidate_batch_with_llm(
            llm_config=llm_config,
            memories=[{"id": "m1", "text": "Alice loves coffee."}],
            union_observations=[],
            union_source_facts={},
            config=_fake_config(),
            remaining_slots=None,
        )

        assert captured["response_format"] is _ConsolidationBatchResponse
        assert "## CAPACITY" not in captured["prompt"]

    @pytest.mark.asyncio
    async def test_zero_slots_emits_max_length_zero_model_and_banner(self) -> None:
        captured: dict[str, Any] = {}

        async def fake_call(*, messages, response_format, scope):
            captured["response_format"] = response_format
            captured["prompt"] = messages[0]["content"]
            return _ConsolidationBatchResponse()

        llm_config = SimpleNamespace(call=AsyncMock(side_effect=fake_call))

        await _consolidate_batch_with_llm(
            llm_config=llm_config,
            memories=[{"id": "m1", "text": "Alice loves coffee."}],
            union_observations=[],
            union_source_facts={},
            config=_fake_config(),
            remaining_slots=0,
        )

        Model = captured["response_format"]
        assert Model is not _ConsolidationBatchResponse
        # Constrained model rejects any creates
        with pytest.raises(ValidationError):
            Model(creates=[_CreateAction(text="x", source_fact_ids=["a"])])
        # Updates / deletes still flow
        Model(updates=[_UpdateAction(text="x", observation_id="o", source_fact_ids=["a"])])
        # Banner mentions hard stop language
        assert "## CAPACITY" in captured["prompt"]
        assert "reached its observation cap" in captured["prompt"]


# ─── _process_memory_batch end-to-end (mocked I/O) ───────────────────────────


@pytest.mark.asyncio
async def test_process_memory_batch_drops_over_cap_creates(monkeypatch) -> None:
    """At the cap, the defensive create-budget drops any over-cap creates
    even if the LLM ignores the constrained schema, while letting deletes and
    updates flow through. Also verifies delete-before-create ordering."""

    bank_id = "bank-cap"
    obs_id = "11111111-1111-1111-1111-111111111111"
    source_id = "22222222-2222-2222-2222-222222222222"

    memories = [{"id": source_id, "text": "Alice loves coffee.", "tags": ["user:alice"]}]

    # _process_memory_batch fans out _find_related_observations (one per fact).
    async def fake_find_related(memory_engine, bank_id, query, request_context, tags):
        return SimpleNamespace(
            results=[
                MemoryFact(
                    id=obs_id,
                    text="Alice prefers tea.",
                    fact_type="observation",
                    tags=["user:alice"],
                )
            ],
            source_facts={},
        )

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._find_related_observations",
        fake_find_related,
    )

    # LLM returns one delete, one update and TWO creates — even though cap=1.
    async def fake_consolidate(**kwargs):
        return _BatchLLMResult(
            creates=[
                _CreateAction(text="Alice drinks lattes.", source_fact_ids=[source_id]),
                _CreateAction(text="Alice owns a moka pot.", source_fact_ids=[source_id]),
            ],
            updates=[_UpdateAction(text="Alice now prefers coffee.", observation_id=obs_id, source_fact_ids=[source_id])],
            deletes=[_DeleteAction(observation_id=obs_id)],
            obs_count=1,
            prompt_chars=0,
        )

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._consolidate_batch_with_llm",
        fake_consolidate,
    )

    # Track call order across executors
    call_order: list[str] = []

    async def fake_delete(*, conn, bank_id, observation_id):
        call_order.append(f"delete:{observation_id}")

    async def fake_update(**kwargs):
        call_order.append(f"update:{kwargs['observation_id']}")

    async def fake_create(**kwargs):
        call_order.append(f"create:{kwargs['text']}")

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._execute_delete_action",
        fake_delete,
    )
    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._execute_update_action",
        fake_update,
    )
    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._execute_create_action",
        fake_create,
    )

    # _count_observations_for_scope is called twice (pre-LLM, post-delete).
    # First call: 0 observations exist -> remaining_slots = cap (1)
    # Second call (post-delete): we report 0 again -> creates_budget = 1
    counts = iter([0, 0])

    async def fake_count(*, conn, bank_id, scope_tags):
        return next(counts)

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._count_observations_for_scope",
        fake_count,
    )

    # Skip duplicate telemetry entirely
    async def fake_dups(**kwargs):
        from atulya_api.engine.consolidation.consolidator import _DuplicateTelemetry

        return _DuplicateTelemetry()

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._collect_duplicate_telemetry",
        fake_dups,
    )

    conn = AsyncMock()
    memory_engine = SimpleNamespace()

    result = await _process_memory_batch(
        conn=conn,
        memory_engine=memory_engine,
        llm_config=SimpleNamespace(),
        bank_id=bank_id,
        memories=memories,
        request_context=SimpleNamespace(),
        config=_fake_config(max_observations_per_scope=1),
    )

    # Delete must happen first, then update, then at most 1 create
    assert call_order[0].startswith("delete:")
    assert call_order[1].startswith("update:")
    create_calls = [c for c in call_order if c.startswith("create:")]
    assert len(create_calls) == 1, f"Expected exactly 1 create, got: {create_calls}"
    # Specifically the FIRST create from the LLM survived; the second was dropped
    assert create_calls[0] == "create:Alice drinks lattes."
    assert result.deleted_count == 1


@pytest.mark.asyncio
async def test_process_memory_batch_untagged_scope_is_exempt(monkeypatch) -> None:
    """When the scope has no tags, the cap is not applied: every create flows."""

    bank_id = "bank-cap"
    source_id = "22222222-2222-2222-2222-222222222222"

    memories = [{"id": source_id, "text": "Random fact.", "tags": []}]

    async def fake_find_related(memory_engine, bank_id, query, request_context, tags):
        return SimpleNamespace(results=[], source_facts={})

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._find_related_observations",
        fake_find_related,
    )

    async def fake_consolidate(**kwargs):
        # If the cap were applied, the constrained model would have max_length=0.
        # Verify remaining_slots is None for untagged scopes.
        assert kwargs.get("remaining_slots") is None
        return _BatchLLMResult(
            creates=[
                _CreateAction(text="A", source_fact_ids=[source_id]),
                _CreateAction(text="B", source_fact_ids=[source_id]),
                _CreateAction(text="C", source_fact_ids=[source_id]),
            ],
            obs_count=0,
            prompt_chars=0,
        )

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._consolidate_batch_with_llm",
        fake_consolidate,
    )

    create_count = 0

    async def fake_create(**kwargs):
        nonlocal create_count
        create_count += 1

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._execute_create_action",
        fake_create,
    )

    # _count_observations_for_scope must NOT be hit because scope is untagged.
    async def fake_count(*, conn, bank_id, scope_tags):  # pragma: no cover - guard
        raise AssertionError("count must not be queried for untagged scope")

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._count_observations_for_scope",
        fake_count,
    )

    async def fake_dups(**kwargs):
        from atulya_api.engine.consolidation.consolidator import _DuplicateTelemetry

        return _DuplicateTelemetry()

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._collect_duplicate_telemetry",
        fake_dups,
    )

    conn = AsyncMock()
    memory_engine = SimpleNamespace()

    await _process_memory_batch(
        conn=conn,
        memory_engine=memory_engine,
        llm_config=SimpleNamespace(),
        bank_id=bank_id,
        memories=memories,
        request_context=SimpleNamespace(),
        config=_fake_config(max_observations_per_scope=1),
    )

    assert create_count == 3


class TestParseObservationScopes:
    """Direct tests for the JSONB parse guard used by ``run_consolidation_job``."""

    def test_passthrough_native_python_value(self) -> None:
        # When the column already arrives as a native Python value (None / list /
        # dict — e.g. when asyncpg's JSONB codec is configured), we return it as-is.
        assert _parse_observation_scopes(None) is None
        assert _parse_observation_scopes([["a"], ["b"]]) == [["a"], ["b"]]
        assert _parse_observation_scopes(["per_tag"]) == ["per_tag"]

    def test_decodes_json_string(self) -> None:
        assert _parse_observation_scopes('"combined"') == "combined"
        assert _parse_observation_scopes('[["alice"], ["ben"]]') == [["alice"], ["ben"]]
        assert _parse_observation_scopes("null") is None

    def test_malformed_json_falls_back_to_none(self) -> None:
        # Must NOT raise — graceful fallback to single combined pass.
        assert _parse_observation_scopes("not-json", bank_id="b") is None
        assert _parse_observation_scopes("{not even close", bank_id="b") is None


@pytest.mark.asyncio
async def test_process_memory_batch_per_pass_cap_enforcement(monkeypatch) -> None:
    """When ``observation_scopes`` triggers multiple passes, the cap must be
    enforced *per pass* (not globally) — so each pass independently asks for
    its own ``remaining_slots`` from the DB. This guarantees ``per_tag``,
    ``combined`` and ``all_combinations`` all behave identically with respect
    to the cap: each tag-scope gets its own budget."""

    bank_id = "bank-cap"
    source_id = "22222222-2222-2222-2222-222222222222"

    memories = [
        {"id": source_id, "text": "Alice and Ben.", "tags": ["user:alice", "teacher:ben"]},
    ]

    # Simulate two passes (per_tag) by calling _process_memory_batch twice
    # with different obs_tags_override values, asserting the cap is consulted
    # for each scope independently.
    scope_calls: list[list[str] | None] = []

    async def fake_count(*, conn, bank_id, scope_tags):
        scope_calls.append(list(scope_tags) if scope_tags else None)
        return 0  # Each scope is empty → full slots available

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._count_observations_for_scope",
        fake_count,
    )

    async def fake_find_related(memory_engine, bank_id, query, request_context, tags):
        return SimpleNamespace(results=[], source_facts={})

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._find_related_observations",
        fake_find_related,
    )

    async def fake_consolidate(**kwargs):
        return _BatchLLMResult(creates=[], obs_count=0, prompt_chars=0)

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._consolidate_batch_with_llm",
        fake_consolidate,
    )

    async def fake_dups(**kwargs):
        from atulya_api.engine.consolidation.consolidator import _DuplicateTelemetry

        return _DuplicateTelemetry()

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._collect_duplicate_telemetry",
        fake_dups,
    )

    conn = AsyncMock()
    memory_engine = SimpleNamespace()
    config = _fake_config(max_observations_per_scope=3)

    # Pass 1 — scope = ["user:alice"]
    await _process_memory_batch(
        conn=conn,
        memory_engine=memory_engine,
        llm_config=SimpleNamespace(),
        bank_id=bank_id,
        memories=memories,
        request_context=SimpleNamespace(),
        config=config,
        obs_tags_override=["user:alice"],
    )
    # Pass 2 — scope = ["teacher:ben"]
    await _process_memory_batch(
        conn=conn,
        memory_engine=memory_engine,
        llm_config=SimpleNamespace(),
        bank_id=bank_id,
        memories=memories,
        request_context=SimpleNamespace(),
        config=config,
        obs_tags_override=["teacher:ben"],
    )

    # Every pass must independently query the DB for its scope; both pre-LLM
    # and post-delete recounts run, so each pass yields 2 scope_calls.
    assert scope_calls == [
        ["user:alice"],
        ["user:alice"],
        ["teacher:ben"],
        ["teacher:ben"],
    ]


@pytest.mark.asyncio
async def test_process_memory_batch_below_limit_unchanged(monkeypatch) -> None:
    """When current_count < cap, remaining_slots = cap - count and all
    LLM-suggested creates flow as long as they fit."""

    bank_id = "bank-cap"
    source_id = "22222222-2222-2222-2222-222222222222"

    memories = [{"id": source_id, "text": "Alice loves coffee.", "tags": ["user:alice"]}]

    async def fake_find_related(memory_engine, bank_id, query, request_context, tags):
        return SimpleNamespace(results=[], source_facts={})

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._find_related_observations",
        fake_find_related,
    )

    captured: dict[str, Any] = {}

    async def fake_consolidate(**kwargs):
        captured["remaining_slots"] = kwargs.get("remaining_slots")
        return _BatchLLMResult(
            creates=[
                _CreateAction(text="A", source_fact_ids=[source_id]),
                _CreateAction(text="B", source_fact_ids=[source_id]),
            ],
            obs_count=0,
            prompt_chars=0,
        )

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._consolidate_batch_with_llm",
        fake_consolidate,
    )

    create_count = 0

    async def fake_create(**kwargs):
        nonlocal create_count
        create_count += 1

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._execute_create_action",
        fake_create,
    )

    counts = iter([2, 2])  # cap=5, current=2 → remaining=3, post-delete=2 → budget=3

    async def fake_count(*, conn, bank_id, scope_tags):
        return next(counts)

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._count_observations_for_scope",
        fake_count,
    )

    async def fake_dups(**kwargs):
        from atulya_api.engine.consolidation.consolidator import _DuplicateTelemetry

        return _DuplicateTelemetry()

    monkeypatch.setattr(
        "atulya_api.engine.consolidation.consolidator._collect_duplicate_telemetry",
        fake_dups,
    )

    conn = AsyncMock()
    memory_engine = SimpleNamespace()

    await _process_memory_batch(
        conn=conn,
        memory_engine=memory_engine,
        llm_config=SimpleNamespace(),
        bank_id=bank_id,
        memories=memories,
        request_context=SimpleNamespace(),
        config=_fake_config(max_observations_per_scope=5),
    )

    assert captured["remaining_slots"] == 3
    assert create_count == 2  # both LLM creates accepted (2 < 3 budget)
