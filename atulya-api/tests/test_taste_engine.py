"""Mechanical edge-case tests for Taste Studio engine and transforms."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from atulya_api.forge.taste.engine import (
    ASYNC_TRANSFORM_THRESHOLD,
    run_taste_generate,
    run_taste_transform,
    submit_taste_transform,
    taste_catalog_payload,
)
from atulya_api.forge.taste.errors import TasteNotFoundError, TasteValidationError
from atulya_api.forge.taste.materialize import payload_hash
from atulya_api.forge.taste.models import (
    CreateTasteDatasetRequest,
    ImportTasteSetsRequest,
    TasteExportRequest,
    TasteGenerateRequest,
    TasteRetainRequest,
    TasteTransformRequest,
    TransformOpSpec,
    UpdateTasteSetRequest,
)
from atulya_api.forge.taste.transforms.base import TasteTransformContext
from atulya_api.forge.taste.transforms.raw import RawTransform
from atulya_api.forge.taste.transforms.registry import get_transform
from atulya_api.models import RequestContext


async def _ensure_bank(memory, bank_id: str, request_context: RequestContext) -> None:
    await memory.get_bank_profile(bank_id=bank_id, request_context=request_context)


async def _seed_qa_dataset(memory, request_context, *, bank_id: str | None = None) -> tuple[str, str, str]:
    bank_id = bank_id or f"taste-eng-{uuid.uuid4().hex[:8]}"
    await _ensure_bank(memory, bank_id, request_context)
    created = await memory.taste_create_dataset(
        bank_id,
        CreateTasteDatasetRequest(name="Engine QA", schema_type="qa_pair"),
        request_context=request_context,
    )
    dataset_id = created["id"]
    imported = await memory.taste_import_sets(
        bank_id,
        dataset_id,
        ImportTasteSetsRequest(sets=[{"question": "Q1", "answer": "A1"}]),
        request_context=request_context,
    )
    set_id = imported["sets"][0]["id"]
    return bank_id, dataset_id, set_id


def test_taste_catalog_has_transforms_and_exporters():
    catalog = taste_catalog_payload()
    assert any(op["op_id"] == "spellfix_llm" for op in catalog["transform_ops"])
    assert any(ex["adapter_id"] == "openai_chat_jsonl" for ex in catalog["exporters"])
    assert len(catalog["schema_types"]) == 3


def test_payload_hash_is_stable():
    payload = {"messages": [{"role": "user", "content": "hi"}]}
    assert payload_hash(payload) == payload_hash(payload)
    assert payload_hash(payload) != payload_hash({"messages": []})


def test_get_transform_unknown_raises():
    with pytest.raises(TasteValidationError):
        get_transform("not_a_real_op")


@pytest.mark.asyncio
async def test_transform_requires_ops_or_chain(memory, request_context):
    bank_id, dataset_id, _ = await _seed_qa_dataset(memory, request_context)
    with pytest.raises(TasteValidationError, match="ops"):
        await run_taste_transform(
            memory,
            bank_id,
            TasteTransformRequest(dataset_id=dataset_id, preview=True),
            request_context=request_context,
        )


@pytest.mark.asyncio
async def test_transform_rejects_missing_set_ids(memory, request_context):
    bank_id, dataset_id, _ = await _seed_qa_dataset(memory, request_context)
    with pytest.raises(TasteNotFoundError):
        await run_taste_transform(
            memory,
            bank_id,
            TasteTransformRequest(
                dataset_id=dataset_id,
                set_ids=[str(uuid.uuid4())],
                ops=[TransformOpSpec(op="raw")],
                preview=True,
            ),
            request_context=request_context,
        )


@pytest.mark.asyncio
async def test_transform_preview_does_not_persist(memory, request_context):
    bank_id, dataset_id, set_id = await _seed_qa_dataset(memory, request_context)
    before = await memory.taste_get_set(bank_id, set_id, request_context=request_context)

    mock_llm = AsyncMock()
    mock_llm.call = AsyncMock(return_value='{"question":"Q1 polished","answer":"A1"}')
    with patch("atulya_api.forge.taste.engine._resolve_llm", new_callable=AsyncMock) as resolve:
        resolve.return_value = (mock_llm, "mock")
        result = await run_taste_transform(
            memory,
            bank_id,
            TasteTransformRequest(
                dataset_id=dataset_id,
                set_ids=[set_id],
                ops=[TransformOpSpec(op="spellfix_llm")],
                preview=True,
            ),
            request_context=request_context,
        )

    after = await memory.taste_get_set(bank_id, set_id, request_context=request_context)
    assert result["preview"] is True
    assert result["items"][0]["after"]["question"] == "Q1 polished"
    assert after["working_payload"] == before["working_payload"]
    assert not after.get("transform_log")


@pytest.mark.asyncio
async def test_transform_apply_persists_and_logs(memory, request_context):
    bank_id, dataset_id, set_id = await _seed_qa_dataset(memory, request_context)
    mock_llm = AsyncMock()
    mock_llm.call = AsyncMock(return_value='{"question":"Q1 fixed","answer":"A1"}')
    with patch("atulya_api.forge.taste.engine._resolve_llm", new_callable=AsyncMock) as resolve:
        resolve.return_value = (mock_llm, "mock")
        result = await run_taste_transform(
            memory,
            bank_id,
            TasteTransformRequest(
                dataset_id=dataset_id,
                set_ids=[set_id],
                ops=[TransformOpSpec(op="spellfix_llm")],
                preview=False,
            ),
            request_context=request_context,
        )

    updated = await memory.taste_get_set(bank_id, set_id, request_context=request_context)
    assert result["updated_count"] == 1
    assert updated["working_payload"]["question"] == "Q1 fixed"
    assert updated["source_payload"]["question"] == "Q1"
    assert len(updated.get("transform_log") or []) == 1
    assert updated["transform_log"][0]["op_id"] == "spellfix_llm"


@pytest.mark.asyncio
async def test_transform_all_sets_when_no_selection(memory, request_context):
    bank_id, dataset_id, set_id = await _seed_qa_dataset(memory, request_context)
    await memory.taste_import_sets(
        bank_id,
        dataset_id,
        ImportTasteSetsRequest(sets=[{"question": "Q2", "answer": "A2"}]),
        request_context=request_context,
    )

    async def _fake_run(ctx, taste_set, params):
        payload = dict(taste_set.working_payload)
        payload["question"] = f"{payload['question']}-raw"
        from atulya_api.forge.taste.transforms.base import TransformResult

        return TransformResult(payload=payload)

    with patch("atulya_api.forge.taste.engine.get_transform") as get_tf:
        raw = RawTransform()
        raw.run = _fake_run  # type: ignore[method-assign]
        get_tf.return_value = raw
        result = await run_taste_transform(
            memory,
            bank_id,
            TasteTransformRequest(
                dataset_id=dataset_id,
                set_ids=[],
                ops=[TransformOpSpec(op="raw")],
                preview=False,
            ),
            request_context=request_context,
        )

    assert result["updated_count"] == 2
    listed = await memory.taste_list_sets(bank_id, dataset_id, limit=10, offset=0, request_context=request_context)
    questions = {row["working_payload"]["question"] for row in listed["sets"]}
    assert questions == {"Q1-raw", "Q2-raw"}


@pytest.mark.asyncio
async def test_raw_transform_is_identity():
    from atulya_api.forge.taste.models import TasteSet

    taste_set = TasteSet(
        id="s",
        dataset_id="d",
        bank_id="b",
        set_key="k",
        source_payload={"question": "q", "answer": "a"},
        working_payload={"question": "q", "answer": "a"},
    )
    ctx = TasteTransformContext(bank_id="b", schema_type="qa_pair", llm_config=AsyncMock())
    result = await RawTransform().run(ctx, taste_set, {})
    assert result.payload == taste_set.working_payload


@pytest.mark.asyncio
async def test_generate_requires_set_ids(memory, request_context):
    bank_id, dataset_id, _ = await _seed_qa_dataset(memory, request_context)
    with pytest.raises(TasteValidationError, match="set_id"):
        await run_taste_generate(
            memory,
            bank_id,
            dataset_id,
            TasteGenerateRequest(set_ids=[], count=2),
            request_context=request_context,
        )


@pytest.mark.asyncio
async def test_generate_variant_lineage_and_increment(memory, request_context):
    bank_id, dataset_id, set_id = await _seed_qa_dataset(memory, request_context)
    mock_llm = AsyncMock()
    mock_llm.call = AsyncMock(
        return_value='[{"question":"Q1 alt","answer":"A1"},{"question":"Q1 alt2","answer":"A1"}]'
    )
    with patch("atulya_api.forge.taste.engine._resolve_llm", new_callable=AsyncMock) as resolve:
        resolve.return_value = (mock_llm, "mock")
        await run_taste_generate(
            memory,
            bank_id,
            dataset_id,
            TasteGenerateRequest(set_ids=[set_id], count=2),
            request_context=request_context,
        )

    listed = await memory.taste_list_sets(bank_id, dataset_id, limit=20, offset=0, request_context=request_context)
    variants = [row for row in listed["sets"] if row["variant_index"] > 0]
    assert len(variants) == 2
    assert all(row["parent_set_id"] == set_id for row in variants)
    assert {row["variant_index"] for row in variants} == {1, 2}
    assert all(row["source_payload"] == listed["sets"][0]["source_payload"] for row in variants)


@pytest.mark.asyncio
async def test_generate_second_batch_continues_variant_index(memory, request_context):
    bank_id, dataset_id, set_id = await _seed_qa_dataset(memory, request_context)
    mock_llm = AsyncMock()
    mock_llm.call = AsyncMock(
        side_effect=[
            '[{"question":"v1","answer":"A1"},{"question":"v2","answer":"A1"}]',
            '[{"question":"v3","answer":"A1"}]',
        ]
    )

    with patch("atulya_api.forge.taste.engine._resolve_llm", new_callable=AsyncMock) as resolve:
        resolve.return_value = (mock_llm, "mock")
        await run_taste_generate(
            memory, bank_id, dataset_id, TasteGenerateRequest(set_ids=[set_id], count=2), request_context=request_context
        )
        await run_taste_generate(
            memory, bank_id, dataset_id, TasteGenerateRequest(set_ids=[set_id], count=1), request_context=request_context
        )

    listed = await memory.taste_list_sets(bank_id, dataset_id, limit=20, offset=0, request_context=request_context)
    indexes = sorted(row["variant_index"] for row in listed["sets"])
    assert indexes == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_retain_rejects_cross_dataset_sets(memory, request_context):
    bank_id = f"taste-cross-{uuid.uuid4().hex[:8]}"
    await _ensure_bank(memory, bank_id, request_context)
    ds1 = (
        await memory.taste_create_dataset(
            bank_id, CreateTasteDatasetRequest(name="A", schema_type="qa_pair"), request_context=request_context
        )
    )["id"]
    ds2 = (
        await memory.taste_create_dataset(
            bank_id, CreateTasteDatasetRequest(name="B", schema_type="qa_pair"), request_context=request_context
        )
    )["id"]
    s1 = (
        await memory.taste_import_sets(
            bank_id, ds1, ImportTasteSetsRequest(sets=[{"question": "q", "answer": "a"}]), request_context=request_context
        )
    )["sets"][0]["id"]
    s2 = (
        await memory.taste_import_sets(
            bank_id, ds2, ImportTasteSetsRequest(sets=[{"question": "q2", "answer": "a2"}]), request_context=request_context
        )
    )["sets"][0]["id"]

    with pytest.raises(TasteValidationError, match="same dataset"):
        await memory.retain_taste_sets(bank_id, TasteRetainRequest(set_ids=[s1, s2]), request_context=request_context)


@pytest.mark.asyncio
async def test_export_empty_dataset_fails(memory, request_context):
    bank_id = f"taste-empty-{uuid.uuid4().hex[:8]}"
    await _ensure_bank(memory, bank_id, request_context)
    empty_ds = (
        await memory.taste_create_dataset(
            bank_id,
            CreateTasteDatasetRequest(name="Empty", schema_type="qa_pair"),
            request_context=request_context,
        )
    )["id"]
    with pytest.raises(TasteValidationError, match="No taste sets"):
        await memory.export_taste_dataset(
            bank_id,
            TasteExportRequest(dataset_id=empty_ds, adapter_id="openai_chat_jsonl"),
            request_context=request_context,
        )


@pytest.mark.asyncio
async def test_export_subset_only(memory, request_context):
    bank_id, dataset_id, set_id = await _seed_qa_dataset(memory, request_context)
    await memory.taste_import_sets(
        bank_id,
        dataset_id,
        ImportTasteSetsRequest(sets=[{"question": "Q2", "answer": "A2"}]),
        request_context=request_context,
    )
    manifest = await memory.export_taste_dataset(
        bank_id,
        TasteExportRequest(dataset_id=dataset_id, set_ids=[set_id], adapter_id="atr_jsonl"),
        request_context=request_context,
    )
    lines = [line for line in (manifest.get("content") or "").splitlines() if line.strip()]
    assert manifest["record_count"] == 1
    assert len(lines) == 1
    assert "Q1" in lines[0]
    assert "Q2" not in lines[0]


@pytest.mark.asyncio
async def test_delete_dataset_cascades_sets(memory, request_context):
    bank_id, dataset_id, set_id = await _seed_qa_dataset(memory, request_context)
    await memory.taste_delete_dataset(bank_id, dataset_id, request_context=request_context)
    with pytest.raises(TasteNotFoundError):
        await memory.taste_get_set(bank_id, set_id, request_context=request_context)


@pytest.mark.asyncio
async def test_update_set_rejects_invalid_schema_payload(memory, request_context):
    bank_id, dataset_id, set_id = await _seed_qa_dataset(memory, request_context)
    with pytest.raises(TasteValidationError):
        await memory.taste_update_set(
            bank_id,
            set_id,
            UpdateTasteSetRequest(working_payload={"messages": []}),
            request_context=request_context,
        )


@pytest.mark.asyncio
async def test_invalid_dataset_id_surfaces_not_found(memory, request_context):
    bank_id, _, _ = await _seed_qa_dataset(memory, request_context)

    with pytest.raises(TasteNotFoundError, match="Dataset not found"):
        await memory.taste_get_dataset(bank_id, "not-a-uuid", request_context=request_context)


@pytest.mark.asyncio
async def test_invalid_set_id_surfaces_not_found(memory, request_context):
    bank_id, _, _ = await _seed_qa_dataset(memory, request_context)

    with pytest.raises(TasteNotFoundError, match="Set not found"):
        await memory.taste_update_set(
            bank_id,
            "not-a-uuid",
            UpdateTasteSetRequest(taste_tags=["qa"]),
            request_context=request_context,
        )


@pytest.mark.asyncio
async def test_invalid_transform_chain_id_surfaces_not_found(memory, request_context):
    bank_id, dataset_id, _ = await _seed_qa_dataset(memory, request_context)

    with pytest.raises(TasteNotFoundError, match="Transform chain not found"):
        await submit_taste_transform(
            memory,
            bank_id,
            TasteTransformRequest(dataset_id=dataset_id, chain_id="not-a-uuid", preview=True),
            request_context=request_context,
        )


@pytest.mark.asyncio
async def test_import_jsonl_invalid_line(memory, request_context):
    bank_id, dataset_id, _ = await _seed_qa_dataset(memory, request_context)
    with pytest.raises(TasteValidationError, match="Invalid JSONL"):
        await memory.taste_import_sets(
            bank_id,
            dataset_id,
            ImportTasteSetsRequest(jsonl="not valid json"),
            request_context=request_context,
        )


@pytest.mark.asyncio
async def test_import_assigns_incrementing_set_keys(memory, request_context):
    bank_id = f"taste-keys-{uuid.uuid4().hex[:8]}"
    await _ensure_bank(memory, bank_id, request_context)
    dataset_id = (
        await memory.taste_create_dataset(
            bank_id,
            CreateTasteDatasetRequest(name="Keys", schema_type="qa_pair"),
            request_context=request_context,
        )
    )["id"]
    first = await memory.taste_import_sets(
        bank_id,
        dataset_id,
        ImportTasteSetsRequest(sets=[{"question": "q1", "answer": "a1"}], set_key_prefix="row"),
        request_context=request_context,
    )
    second = await memory.taste_import_sets(
        bank_id,
        dataset_id,
        ImportTasteSetsRequest(sets=[{"question": "q2", "answer": "a2"}], set_key_prefix="row"),
        request_context=request_context,
    )
    keys = {first["sets"][0]["set_key"], second["sets"][0]["set_key"]}
    assert keys == {"row_0001", "row_0002"}


@pytest.mark.asyncio
async def test_submit_transform_queues_async_for_large_batches(memory, request_context):
    bank_id, dataset_id, _ = await _seed_qa_dataset(memory, request_context)
    set_ids: list[str] = []
    for i in range(ASYNC_TRANSFORM_THRESHOLD + 1):
        imported = await memory.taste_import_sets(
            bank_id,
            dataset_id,
            ImportTasteSetsRequest(sets=[{"question": f"Q{i}", "answer": f"A{i}"}]),
            request_context=request_context,
        )
        set_ids.append(imported["sets"][0]["id"])

    with patch.object(memory, "_submit_async_operation", new_callable=AsyncMock) as submit:
        submit.return_value = {"operation_id": "op-123", "deduplicated": False}
        result = await submit_taste_transform(
            memory,
            bank_id,
            TasteTransformRequest(
                dataset_id=dataset_id,
                set_ids=set_ids,
                ops=[TransformOpSpec(op="raw")],
                preview=False,
            ),
            request_context=request_context,
        )

    assert result["operation_id"] == "op-123"
    submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_transform_rejects_cross_dataset_set_ids(memory, request_context):
    bank_id = f"taste-xform-{uuid.uuid4().hex[:8]}"
    await _ensure_bank(memory, bank_id, request_context)
    ds1 = (
        await memory.taste_create_dataset(
            bank_id,
            CreateTasteDatasetRequest(name="A", schema_type="qa_pair"),
            request_context=request_context,
        )
    )["id"]
    ds2 = (
        await memory.taste_create_dataset(
            bank_id,
            CreateTasteDatasetRequest(name="B", schema_type="qa_pair"),
            request_context=request_context,
        )
    )["id"]
    s1 = (
        await memory.taste_import_sets(
            bank_id,
            ds1,
            ImportTasteSetsRequest(sets=[{"question": "q", "answer": "a"}]),
            request_context=request_context,
        )
    )["sets"][0]["id"]
    with pytest.raises(TasteValidationError, match="requested dataset"):
        await run_taste_transform(
            memory,
            bank_id,
            TasteTransformRequest(
                dataset_id=ds2,
                set_ids=[s1],
                ops=[TransformOpSpec(op="raw")],
                preview=True,
            ),
            request_context=request_context,
        )


@pytest.mark.asyncio
async def test_revert_after_retain_resets_status_and_memory(memory, request_context):
    bank_id, dataset_id, set_id = await _seed_qa_dataset(memory, request_context)
    with patch.object(memory, "retain_batch_async", new_callable=AsyncMock) as retain_mock:
        retain_mock.return_value = [["mem-1"]]
        await memory.retain_taste_sets(
            bank_id,
            TasteRetainRequest(set_ids=[set_id]),
            request_context=request_context,
        )
    reverted = await memory.taste_revert_set(bank_id, set_id, request_context=request_context)
    assert reverted["status"] == "draft"
    assert reverted["memory_unit_ids"] == []
    assert reverted["transform_log"] == []


@pytest.mark.asyncio
async def test_double_retain_rejected(memory, request_context):
    bank_id, dataset_id, set_id = await _seed_qa_dataset(memory, request_context)
    with patch.object(memory, "retain_batch_async", new_callable=AsyncMock) as retain_mock:
        retain_mock.return_value = [["mem-1"]]
        await memory.retain_taste_sets(
            bank_id,
            TasteRetainRequest(set_ids=[set_id]),
            request_context=request_context,
        )
        with pytest.raises(TasteValidationError, match="already retained"):
            await memory.retain_taste_sets(
                bank_id,
                TasteRetainRequest(set_ids=[set_id]),
                request_context=request_context,
            )
