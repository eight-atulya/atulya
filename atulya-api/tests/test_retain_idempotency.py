"""
Regression tests for the retain pipeline idempotency contract (Group 2 of the
hindsight bugfix backport).

The bug: the retain pipeline had no documented idempotency guarantee. A retain
task that crashed after writing chunks would, on retry:

* Fail deterministically with a primary-key violation in chunks (chunk_id is
  ``{bank_id}_{document_id}_{chunk_index}`` — same input produces the same id).
* Burn 3 retries before being marked failed because the generic exception
  handler retried every error class.

Independently: ``embedding_utils.generate_embeddings_batch`` had no length
contract. If the backend returned a short batch, the silent truncation
propagated through ``zip(extracted_facts, embeddings)`` and produced
mis-aligned ``ProcessedFact`` rows downstream, eventually surfacing as an
IndexError far from the cause.

These tests assert:

1. ``store_chunks_batch`` is idempotent under same-id re-insertion (chunk
   text is overwritten, no PK violation).
2. ``generate_embeddings_batch`` raises ``EmbeddingBackendContractError`` when
   the backend returns the wrong number of vectors.
3. ``_is_retryable_task_error`` correctly classifies integrity violations and
   embedding-contract errors as non-retryable, and other exceptions as
   retryable.
4. ``_map_results_to_contents`` raises a clear error when the
   processed_facts/unit_ids invariant is violated.
"""

import uuid

import asyncpg
import pytest

from atulya_api import RequestContext
from atulya_api.engine.memory_engine import MemoryEngine, _is_retryable_task_error
from atulya_api.engine.retain.chunk_storage import store_chunks_batch
from atulya_api.engine.retain.embedding_utils import (
    EmbeddingBackendContractError,
    generate_embeddings_batch,
)
from atulya_api.engine.retain.orchestrator import _map_results_to_contents
from atulya_api.engine.retain.types import ChunkMetadata, ProcessedFact, RetainContent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_bank_and_document(
    memory: MemoryEngine, bank_id: str, document_id: str, request_context: RequestContext
):
    await memory.get_bank_profile(bank_id=bank_id, request_context=request_context)
    pool = await memory._get_pool()
    async with pool.acquire() as conn:
        # documents PK is (id, bank_id); chunks FK to (document_id, bank_id)
        await conn.execute(
            """
            INSERT INTO documents (id, bank_id, created_at, updated_at)
            VALUES ($1, $2, NOW(), NOW())
            ON CONFLICT (id, bank_id) DO NOTHING
            """,
            document_id,
            bank_id,
        )


def _make_processed_fact(text: str, content_index: int) -> ProcessedFact:
    """Construct a ProcessedFact with the minimum required fields."""
    return ProcessedFact(
        fact_text=text,
        fact_type="world",
        embedding=[0.0],
        occurred_start=None,
        occurred_end=None,
        mentioned_at=None,
        timeline_anchor_kind="recorded_only",
        temporal_direction="atemporal",
        temporal_confidence=None,
        temporal_reference_text=None,
        context="",
        metadata={},
        content_index=content_index,
    )


# ---------------------------------------------------------------------------
# chunk_storage idempotency
# ---------------------------------------------------------------------------


class TestChunkStorageIdempotency:
    @pytest.mark.asyncio
    async def test_resubmit_same_chunks_overwrites_text(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        """Calling store_chunks_batch twice with the same chunk_id must
        succeed (no PK violation) and overwrite the chunk_text.
        """
        bank_id = f"test-retain-idem-{uuid.uuid4().hex[:8]}"
        document_id = f"doc-{uuid.uuid4().hex[:8]}"
        await _ensure_bank_and_document(memory, bank_id, document_id, request_context)

        pool = await memory._get_pool()
        chunks_v1 = [
            ChunkMetadata(chunk_text="version 1 - chunk 0", fact_count=1, chunk_index=0, content_index=0),
            ChunkMetadata(chunk_text="version 1 - chunk 1", fact_count=1, chunk_index=1, content_index=0),
        ]
        chunks_v2 = [
            ChunkMetadata(chunk_text="version 2 - chunk 0", fact_count=1, chunk_index=0, content_index=0),
            ChunkMetadata(chunk_text="version 2 - chunk 1", fact_count=1, chunk_index=1, content_index=0),
        ]

        async with pool.acquire() as conn:
            map_v1 = await store_chunks_batch(conn, bank_id, document_id, chunks_v1)
            map_v2 = await store_chunks_batch(conn, bank_id, document_id, chunks_v2)

        # The chunk_id mapping is deterministic; both calls must return the same map.
        assert map_v1 == map_v2

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT chunk_index, chunk_text FROM chunks WHERE bank_id = $1 AND document_id = $2 ORDER BY chunk_index",
                bank_id,
                document_id,
            )
        assert len(rows) == 2, "Re-insertion must not duplicate rows"
        assert rows[0]["chunk_text"] == "version 2 - chunk 0"
        assert rows[1]["chunk_text"] == "version 2 - chunk 1"

        await memory.delete_bank(bank_id, request_context=request_context)

    @pytest.mark.asyncio
    async def test_empty_chunks_is_noop(self, memory: MemoryEngine, request_context: RequestContext):
        bank_id = f"test-retain-idem-empty-{uuid.uuid4().hex[:8]}"
        document_id = f"doc-{uuid.uuid4().hex[:8]}"
        await _ensure_bank_and_document(memory, bank_id, document_id, request_context)

        pool = await memory._get_pool()
        async with pool.acquire() as conn:
            assert await store_chunks_batch(conn, bank_id, document_id, []) == {}

        await memory.delete_bank(bank_id, request_context=request_context)


# ---------------------------------------------------------------------------
# generate_embeddings_batch length contract
# ---------------------------------------------------------------------------


class _FixedLengthBackend:
    """Test backend that returns ``n_returned`` vectors regardless of input."""

    def __init__(self, n_returned: int, dim: int = 4):
        self.n_returned = n_returned
        self.dim = dim

    def encode(self, texts):
        return [[0.0] * self.dim for _ in range(self.n_returned)]


class TestEmbeddingBackendContract:
    @pytest.mark.asyncio
    async def test_short_batch_raises_with_diagnostic(self):
        backend = _FixedLengthBackend(n_returned=2)
        with pytest.raises(EmbeddingBackendContractError) as ei:
            await generate_embeddings_batch(backend, ["a", "b", "c"])
        msg = str(ei.value)
        assert "2 vectors" in msg
        assert "3 input texts" in msg

    @pytest.mark.asyncio
    async def test_long_batch_raises_with_diagnostic(self):
        backend = _FixedLengthBackend(n_returned=4)
        with pytest.raises(EmbeddingBackendContractError) as ei:
            await generate_embeddings_batch(backend, ["a", "b", "c"])
        msg = str(ei.value)
        assert "4 vectors" in msg
        assert "3 input texts" in msg

    @pytest.mark.asyncio
    async def test_exact_match_returns_embeddings(self):
        backend = _FixedLengthBackend(n_returned=3)
        result = await generate_embeddings_batch(backend, ["a", "b", "c"])
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        backend = _FixedLengthBackend(n_returned=99)
        # Empty input must not invoke the backend at all
        assert await generate_embeddings_batch(backend, []) == []


# ---------------------------------------------------------------------------
# _is_retryable_task_error policy
# ---------------------------------------------------------------------------


class TestRetryClassifier:
    def test_unique_violation_not_retryable(self):
        exc = asyncpg.exceptions.UniqueViolationError("dup key")
        assert _is_retryable_task_error(exc) is False

    def test_foreign_key_violation_not_retryable(self):
        exc = asyncpg.exceptions.ForeignKeyViolationError("missing fk")
        assert _is_retryable_task_error(exc) is False

    def test_check_violation_not_retryable(self):
        exc = asyncpg.exceptions.CheckViolationError("bad check")
        assert _is_retryable_task_error(exc) is False

    def test_not_null_violation_not_retryable(self):
        exc = asyncpg.exceptions.NotNullViolationError("null col")
        assert _is_retryable_task_error(exc) is False

    def test_embedding_contract_not_retryable(self):
        exc = EmbeddingBackendContractError("len mismatch")
        assert _is_retryable_task_error(exc) is False

    def test_generic_exception_retryable(self):
        assert _is_retryable_task_error(RuntimeError("transient")) is True
        assert _is_retryable_task_error(TimeoutError()) is True
        assert _is_retryable_task_error(ConnectionResetError()) is True


# ---------------------------------------------------------------------------
# _map_results_to_contents invariant
# ---------------------------------------------------------------------------


class TestMapResultsInvariant:
    def test_alignment_correct_when_processed_facts_match_unit_ids(self):
        contents = [RetainContent(content="c0"), RetainContent(content="c1")]
        pf0 = _make_processed_fact("f0", content_index=0)
        pf1 = _make_processed_fact("f1", content_index=1)
        unit_ids = ["u0", "u1"]
        result = _map_results_to_contents(contents, [pf0, pf1], unit_ids)
        assert result == [["u0"], ["u1"]]

    def test_multiple_facts_per_content_mapped_correctly(self):
        contents = [RetainContent(content="c0"), RetainContent(content="c1")]
        pfs = [
            _make_processed_fact("f0", content_index=0),
            _make_processed_fact("f1", content_index=0),
            _make_processed_fact("f2", content_index=1),
        ]
        unit_ids = ["u0", "u1", "u2"]
        result = _map_results_to_contents(contents, pfs, unit_ids)
        assert result == [["u0", "u1"], ["u2"]]

    def test_invariant_violation_raises_with_diagnostic(self):
        contents = [RetainContent(content="c0")]
        pfs = [_make_processed_fact("f0", content_index=0)]
        # Mismatched unit_ids length → invariant violated
        with pytest.raises(RuntimeError) as ei:
            _map_results_to_contents(contents, pfs, ["u0", "u1"])
        assert "1 processed_facts" in str(ei.value)
        assert "2 unit_ids" in str(ei.value)

    def test_empty_inputs_produce_empty_buckets(self):
        contents = [RetainContent(content="c0"), RetainContent(content="c1")]
        result = _map_results_to_contents(contents, [], [])
        assert result == [[], []]


# ---------------------------------------------------------------------------
# Sync embedding API removal
# ---------------------------------------------------------------------------


class TestSyncEmbeddingApiRemoved:
    def test_sync_generate_embedding_no_longer_exists(self):
        from atulya_api.engine.retain import embedding_utils

        # The sync generate_embedding helper was deliberately removed because it
        # blocked the event loop on the recall hot path and served as an
        # attractor for new sync callers. Async callers must use
        # generate_embeddings_batch.
        assert not hasattr(embedding_utils, "generate_embedding"), (
            "embedding_utils.generate_embedding must remain removed; use "
            "generate_embeddings_batch from async code instead"
        )
