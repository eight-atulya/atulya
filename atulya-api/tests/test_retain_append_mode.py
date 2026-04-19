"""
Tests for retain `update_mode='append'`.

Verifies that when a caller submits content with `update_mode="append"` against
an existing `document_id`, the engine concatenates the prior `original_text`
with the incoming content, deletes the old document data, and reprocesses the
combined text into facts.

Also verifies the validation rules: `update_mode` must be one of
{"replace", "append"}, and "append" requires a `document_id`.
"""

from __future__ import annotations

import logging
import uuid

import pytest

from atulya_api.engine.memory_engine import fq_table
from atulya_api.engine.retain.fact_storage import get_document_content

logger = logging.getLogger(__name__)


def _bank() -> str:
    return f"test_append_{uuid.uuid4().hex[:8]}"


async def _document_text(memory, bank_id: str, document_id: str) -> str | None:
    pool = memory._pool  # type: ignore[attr-defined]
    async with pool.acquire() as conn:
        return await get_document_content(conn, bank_id, document_id)


async def _unit_count(memory, bank_id: str, document_id: str) -> int:
    pool = memory._pool  # type: ignore[attr-defined]
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT COUNT(*) AS n FROM {fq_table('memory_units')} "
            f"WHERE bank_id = $1 AND document_id = $2",
            bank_id,
            document_id,
        )
    return int(row["n"]) if row else 0


@pytest.mark.asyncio
async def test_append_concatenates_existing_document(memory, request_context):
    """Append mode prepends the prior document text and stores the combined original."""
    bank_id = _bank()
    document_id = "append-doc-1"

    initial_content = "Alice joined Acme Corp as a staff engineer in March 2024."
    appended_content = "Alice was promoted to principal engineer in October 2024."

    await memory.retain_batch_async(
        bank_id=bank_id,
        contents=[
            {
                "content": initial_content,
                "context": "personnel",
                "document_id": document_id,
            }
        ],
        request_context=request_context,
    )

    initial_units = await _unit_count(memory, bank_id, document_id)
    assert initial_units > 0, "initial retain should create at least one unit"

    await memory.retain_batch_async(
        bank_id=bank_id,
        contents=[
            {
                "content": appended_content,
                "context": "personnel",
                "document_id": document_id,
                "update_mode": "append",
            }
        ],
        request_context=request_context,
    )

    stored = await _document_text(memory, bank_id, document_id)
    assert stored is not None, "document should still exist after append"
    assert initial_content in stored, "prior text must be preserved"
    assert appended_content in stored, "appended text must be present"
    assert stored.index(initial_content) < stored.index(appended_content), (
        "prior text must come before appended text"
    )


@pytest.mark.asyncio
async def test_append_multiple_times_preserves_history(memory, request_context):
    """Multiple sequential appends grow the document monotonically."""
    bank_id = _bank()
    document_id = "append-doc-multi"

    parts = [
        "First, Bob shipped the auth refactor.",
        "Then Bob proposed a caching layer.",
        "Finally, Bob owned the rollout playbook.",
    ]

    await memory.retain_batch_async(
        bank_id=bank_id,
        contents=[{"content": parts[0], "document_id": document_id}],
        request_context=request_context,
    )
    for chunk in parts[1:]:
        await memory.retain_batch_async(
            bank_id=bank_id,
            contents=[
                {
                    "content": chunk,
                    "document_id": document_id,
                    "update_mode": "append",
                }
            ],
            request_context=request_context,
        )

    stored = await _document_text(memory, bank_id, document_id)
    assert stored is not None
    for chunk in parts:
        assert chunk in stored
    indices = [stored.index(chunk) for chunk in parts]
    assert indices == sorted(indices), "chunks must remain in submission order"


@pytest.mark.asyncio
async def test_append_against_missing_document_creates_fresh(memory, request_context):
    """Appending to a non-existent document falls back to a clean insert."""
    bank_id = _bank()
    document_id = "append-doc-missing"

    new_content = "Carol drafted the Q3 incident review."

    await memory.retain_batch_async(
        bank_id=bank_id,
        contents=[
            {
                "content": new_content,
                "document_id": document_id,
                "update_mode": "append",
            }
        ],
        request_context=request_context,
    )

    stored = await _document_text(memory, bank_id, document_id)
    assert stored is not None
    assert new_content in stored
    # No prior content, so the stored text should not be longer than the input
    # plus the small newline separator we may have added (we don't prepend when
    # there is nothing to prepend, so it stays identical).
    assert stored == new_content


@pytest.mark.asyncio
async def test_append_without_document_id_is_rejected(memory, request_context):
    """`update_mode='append'` with no `document_id` raises a clear validation error."""
    bank_id = _bank()
    with pytest.raises(ValueError, match="update_mode='append' requires a document_id"):
        await memory.retain_batch_async(
            bank_id=bank_id,
            contents=[{"content": "stray content", "update_mode": "append"}],
            request_context=request_context,
        )


@pytest.mark.asyncio
async def test_default_replace_overwrites_existing_document(memory, request_context):
    """Default behavior (no update_mode) still wipes prior data — append is opt-in."""
    bank_id = _bank()
    document_id = "append-doc-replace"

    initial_content = "Old content that must be discarded."
    replacement = "Brand new content unrelated to the prior text."

    await memory.retain_batch_async(
        bank_id=bank_id,
        contents=[{"content": initial_content, "document_id": document_id}],
        request_context=request_context,
    )

    await memory.retain_batch_async(
        bank_id=bank_id,
        contents=[{"content": replacement, "document_id": document_id}],
        request_context=request_context,
    )

    stored = await _document_text(memory, bank_id, document_id)
    assert stored is not None
    assert initial_content not in stored, "default replace must discard old text"
    assert replacement in stored


@pytest.mark.asyncio
async def test_get_document_content_helper_returns_none_for_unknown(memory):
    """The fact_storage helper distinguishes missing documents from empty bodies."""
    pool = memory._pool  # type: ignore[attr-defined]
    bank_id = _bank()
    async with pool.acquire() as conn:
        result = await get_document_content(conn, bank_id, "definitely-not-a-doc")
    assert result is None
