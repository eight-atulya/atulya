"""Integration tests for Taste Studio store and API flows."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from atulya_api.engine.memory_engine import MemoryEngine
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
from atulya_api.forge.taste.retain import taste_set_to_retain_item
from atulya_api.models import RequestContext


async def _ensure_bank(memory: MemoryEngine, bank_id: str, request_context: RequestContext) -> None:
    await memory.get_bank_profile(bank_id=bank_id, request_context=request_context)


@pytest.mark.asyncio
async def test_taste_dataset_crud_and_import(memory, request_context):
    bank_id = f"taste-store-{uuid.uuid4().hex[:8]}"
    await _ensure_bank(memory, bank_id, request_context)

    created = await memory.taste_create_dataset(
        bank_id,
        CreateTasteDatasetRequest(name="Support tone", schema_type="openai_chat"),
        request_context=request_context,
    )
    dataset_id = created["id"]

    imported = await memory.taste_import_sets(
        bank_id,
        dataset_id,
        ImportTasteSetsRequest(
            sets=[
                {
                    "messages": [
                        {"role": "user", "content": "Refund policy?"},
                        {"role": "assistant", "content": "30 days with receipt."},
                    ]
                }
            ]
        ),
        request_context=request_context,
    )
    assert imported["imported_count"] == 1
    set_id = imported["sets"][0]["id"]

    listed = await memory.taste_list_sets(bank_id, dataset_id, limit=10, offset=0, request_context=request_context)
    assert listed["total"] == 1

    updated = await memory.taste_update_set(
        bank_id,
        set_id,
        UpdateTasteSetRequest(
            working_payload={
                "messages": [
                    {"role": "user", "content": "Refund policy?"},
                    {"role": "assistant", "content": "Refunds within 30 days with receipt."},
                ]
            },
            status="ready",
        ),
        request_context=request_context,
    )
    assert updated["status"] == "ready"

    reverted = await memory.taste_revert_set(bank_id, set_id, request_context=request_context)
    assert reverted["working_payload"] == reverted["source_payload"]


def test_taste_retain_adapter_tags():
    from atulya_api.forge.taste.models import TasteSet

    item = taste_set_to_retain_item(
        TasteSet(
            id="s1",
            dataset_id="d1",
            bank_id="b1",
            set_key="set_0001",
            source_payload={"messages": [{"role": "user", "content": "Hi"}]},
            working_payload={"messages": [{"role": "user", "content": "Hi"}]},
            taste_tags=["tone:concise"],
        ),
        schema_type="openai_chat",
        dataset_id="d1",
    )
    assert "taste:dataset:d1" in item["tags"]
    assert "tone:concise" in item["tags"]


@pytest.mark.asyncio
async def test_taste_export_dataset(memory, request_context):
    bank_id = f"taste-export-{uuid.uuid4().hex[:8]}"
    await _ensure_bank(memory, bank_id, request_context)
    created = await memory.taste_create_dataset(
        bank_id,
        CreateTasteDatasetRequest(name="Export set", schema_type="qa_pair"),
        request_context=request_context,
    )
    dataset_id = created["id"]
    await memory.taste_import_sets(
        bank_id,
        dataset_id,
        ImportTasteSetsRequest(sets=[{"question": "Q", "answer": "A"}]),
        request_context=request_context,
    )

    from atulya_api.forge.taste.models import TasteExportRequest

    manifest = await memory.export_taste_dataset(
        bank_id,
        TasteExportRequest(dataset_id=dataset_id, adapter_id="openai_chat_jsonl"),
        request_context=request_context,
    )
    assert manifest["exportable_count"] >= 1
    assert "messages" in (manifest.get("content") or "")


@pytest.mark.asyncio
async def test_taste_transform_preview_with_mock_llm(memory, request_context):
    bank_id = f"taste-transform-{uuid.uuid4().hex[:8]}"
    await _ensure_bank(memory, bank_id, request_context)
    created = await memory.taste_create_dataset(
        bank_id,
        CreateTasteDatasetRequest(name="Transform", schema_type="qa_pair"),
        request_context=request_context,
    )
    dataset_id = created["id"]
    imported = await memory.taste_import_sets(
        bank_id,
        dataset_id,
        ImportTasteSetsRequest(sets=[{"question": "Helo world?", "answer": "It is Earth."}]),
        request_context=request_context,
    )
    set_id = imported["sets"][0]["id"]

    from atulya_api.forge.taste.engine import run_taste_transform

    mock_llm = AsyncMock()
    mock_llm.call = AsyncMock(return_value='{"question":"Hello world?","answer":"It is Earth."}')

    with patch("atulya_api.forge.taste.engine._resolve_llm", new_callable=AsyncMock) as resolve:
        resolve.return_value = (mock_llm, "mock-model")
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

    assert result["preview"] is True
    assert result["items"][0]["before"]["question"] == "Helo world?"
    assert result["items"][0]["after"]["question"] == "Hello world?"


@pytest.mark.asyncio
async def test_taste_generate_variants_with_mock_llm(memory, request_context):
    bank_id = f"taste-variant-{uuid.uuid4().hex[:8]}"
    await _ensure_bank(memory, bank_id, request_context)
    created = await memory.taste_create_dataset(
        bank_id,
        CreateTasteDatasetRequest(name="Variants", schema_type="qa_pair"),
        request_context=request_context,
    )
    dataset_id = created["id"]
    imported = await memory.taste_import_sets(
        bank_id,
        dataset_id,
        ImportTasteSetsRequest(sets=[{"question": "Capital of France?", "answer": "Paris"}]),
        request_context=request_context,
    )
    set_id = imported["sets"][0]["id"]

    mock_llm = AsyncMock()
    mock_llm.call = AsyncMock(
        return_value='[{"question":"What is France\'s capital?","answer":"Paris"},{"question":"France capital?","answer":"Paris"}]'
    )

    from atulya_api.forge.taste.engine import run_taste_generate

    with patch("atulya_api.forge.taste.engine._resolve_llm", new_callable=AsyncMock) as resolve:
        resolve.return_value = (mock_llm, "mock-model")
        result = await run_taste_generate(
            memory,
            bank_id,
            dataset_id,
            TasteGenerateRequest(
                set_ids=[set_id],
                count=2,
            ),
            request_context=request_context,
        )

    assert result["created_count"] == 2
    listed = await memory.taste_list_sets(bank_id, dataset_id, limit=20, offset=0, request_context=request_context)
    assert listed["total"] == 3


@pytest.mark.asyncio
async def test_taste_retain_updates_set(memory, request_context):
    bank_id = f"taste-retain-{uuid.uuid4().hex[:8]}"
    await _ensure_bank(memory, bank_id, request_context)
    created = await memory.taste_create_dataset(
        bank_id,
        CreateTasteDatasetRequest(name="Retain", schema_type="openai_chat"),
        request_context=request_context,
    )
    dataset_id = created["id"]
    imported = await memory.taste_import_sets(
        bank_id,
        dataset_id,
        ImportTasteSetsRequest(sets=[{"messages": [{"role": "user", "content": "Store this in memory"}]}]),
        request_context=request_context,
    )
    set_id = imported["sets"][0]["id"]

    with patch.object(memory, "retain_batch_async", new_callable=AsyncMock) as retain_mock:
        retain_mock.return_value = [["mem-1"]]
        result = await memory.retain_taste_sets(
            bank_id,
            TasteRetainRequest(set_ids=[set_id]),
            request_context=request_context,
        )

    assert result["retained_count"] == 1
    updated = await memory.taste_get_set(bank_id, set_id, request_context=request_context)
    assert updated["status"] == "retained"
    assert updated["memory_unit_ids"] == ["mem-1"]
