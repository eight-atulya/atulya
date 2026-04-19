"""
Regression tests for the orphan-observation race fix (Group 1 of the hindsight
bugfix backport).

The bug: consolidation reads a source memory, calls an LLM for several seconds,
then writes an observation referencing that source. If the source memory was
hard-deleted during the LLM call, the observation landed referencing a
now-missing uuid because the delete's stale-observation sweep had already run
and could not see the not-yet-inserted row. ``source_memory_ids`` is a
``uuid[]`` column on ``memory_units``, so Postgres cannot FK-cascade through
it.

The fix is two coordinated changes:

1. ``consolidator._filter_live_source_memories`` filters source ids against
   live rows with ``SELECT ... FOR SHARE`` inside the same transaction as
   the INSERT/UPDATE. Drops any id whose row was deleted; blocks concurrent
   deletes until the write commits. Skips the create/update entirely when no
   live sources remain.
2. ``MemoryEngine.delete_document`` / ``delete_memory_unit`` /
   ``delete_bank(fact_type=...)`` now run the stale-observation sweep AFTER
   the delete, so any observation that was inserted concurrently (between the
   old sweep and the delete) is also caught under READ COMMITTED.

These tests exercise the consolidator helpers directly with mixed live/dead
and all-dead ``source_memory_ids``, and assert the orphan invariant
(no observation references a missing source) holds across the suite.
"""

import uuid

import pytest

from atulya_api import RequestContext
from atulya_api.engine.consolidation.consolidator import (
    _create_observation_directly,
    _execute_update_action,
    _filter_live_source_memories,
)
from atulya_api.engine.memory_engine import MemoryEngine
from atulya_api.engine.response_models import MemoryFact

# ---------------------------------------------------------------------------
# Helpers (kept small and local to avoid coupling to other test files)
# ---------------------------------------------------------------------------


async def _insert_memory(conn, bank_id: str, text: str, fact_type: str = "experience") -> uuid.UUID:
    mem_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO memory_units (id, bank_id, text, fact_type, event_date, created_at, updated_at, consolidated_at)
        VALUES ($1, $2, $3, $4, NOW(), NOW(), NOW(), NOW())
        """,
        mem_id,
        bank_id,
        text,
        fact_type,
    )
    return mem_id


async def _insert_observation(
    conn, bank_id: str, text: str, source_memory_ids: list[uuid.UUID]
) -> uuid.UUID:
    obs_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO memory_units (
            id, bank_id, text, fact_type, event_date, source_memory_ids, proof_count, created_at, updated_at
        ) VALUES ($1, $2, $3, 'observation', NOW(), $4, $5, NOW(), NOW())
        """,
        obs_id,
        bank_id,
        text,
        source_memory_ids,
        len(source_memory_ids),
    )
    return obs_id


async def _ensure_bank(memory: MemoryEngine, bank_id: str, request_context: RequestContext):
    await memory.get_bank_profile(bank_id=bank_id, request_context=request_context)


async def _count_orphan_observations(conn, bank_id: str) -> int:
    """Return the number of observations in this bank whose source_memory_ids
    contain at least one uuid not present in memory_units. This is the
    invariant the bug violated; it must always be 0 after the fix.
    """
    row = await conn.fetchrow(
        """
        SELECT COUNT(*) AS n
        FROM memory_units obs
        WHERE obs.bank_id = $1
          AND obs.fact_type = 'observation'
          AND obs.source_memory_ids IS NOT NULL
          AND array_length(obs.source_memory_ids, 1) > 0
          AND EXISTS (
              SELECT 1
              FROM unnest(obs.source_memory_ids) AS sid
              WHERE NOT EXISTS (
                  SELECT 1 FROM memory_units src WHERE src.id = sid
              )
          )
        """,
        bank_id,
    )
    return int(row["n"])


# ---------------------------------------------------------------------------
# Unit-level: _filter_live_source_memories
# ---------------------------------------------------------------------------


class TestFilterLiveSourceMemories:
    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_input(self, memory: MemoryEngine, request_context: RequestContext):
        bank_id = f"test-orphan-empty-{uuid.uuid4().hex[:8]}"
        await _ensure_bank(memory, bank_id, request_context)

        pool = await memory._get_pool()
        async with pool.acquire() as conn:
            assert await _filter_live_source_memories(conn, bank_id, []) == []

        await memory.delete_bank(bank_id, request_context=request_context)

    @pytest.mark.asyncio
    async def test_returns_only_live_ids_preserving_order(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        bank_id = f"test-orphan-mixed-{uuid.uuid4().hex[:8]}"
        await _ensure_bank(memory, bank_id, request_context)

        pool = await memory._get_pool()
        async with pool.acquire() as conn:
            m1 = await _insert_memory(conn, bank_id, "live 1")
            m2 = await _insert_memory(conn, bank_id, "live 2")
            dead = uuid.uuid4()  # never inserted
            mixed = [m1, dead, m2]

            live = await _filter_live_source_memories(conn, bank_id, mixed)
            assert live == [m1, m2], "Filter must preserve input order and drop dead ids"

        await memory.delete_bank(bank_id, request_context=request_context)

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_dead(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        bank_id = f"test-orphan-alldead-{uuid.uuid4().hex[:8]}"
        await _ensure_bank(memory, bank_id, request_context)

        pool = await memory._get_pool()
        async with pool.acquire() as conn:
            ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
            assert await _filter_live_source_memories(conn, bank_id, ids) == []

        await memory.delete_bank(bank_id, request_context=request_context)

    @pytest.mark.asyncio
    async def test_excludes_ids_from_other_banks(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        """A memory id that exists in a different bank must not count as live."""
        bank_a = f"test-orphan-banka-{uuid.uuid4().hex[:8]}"
        bank_b = f"test-orphan-bankb-{uuid.uuid4().hex[:8]}"
        await _ensure_bank(memory, bank_a, request_context)
        await _ensure_bank(memory, bank_b, request_context)

        pool = await memory._get_pool()
        async with pool.acquire() as conn:
            m_a = await _insert_memory(conn, bank_a, "in bank A")
            m_b = await _insert_memory(conn, bank_b, "in bank B")
            # Filter against bank_a; m_b must be filtered out even though it exists.
            live = await _filter_live_source_memories(conn, bank_a, [m_a, m_b])
            assert live == [m_a]

        await memory.delete_bank(bank_a, request_context=request_context)
        await memory.delete_bank(bank_b, request_context=request_context)


# ---------------------------------------------------------------------------
# Integration: _create_observation_directly with all-dead sources
# ---------------------------------------------------------------------------


class TestCreateObservationWithDeletedSources:
    @pytest.mark.asyncio
    async def test_create_skipped_when_all_sources_dead(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        """When all source ids are dead by the time we attempt to insert, the
        create must be skipped (no orphan inserted)."""
        bank_id = f"test-orphan-create-skip-{uuid.uuid4().hex[:8]}"
        await _ensure_bank(memory, bank_id, request_context)

        pool = await memory._get_pool()
        async with pool.acquire() as conn:
            dead_ids = [uuid.uuid4(), uuid.uuid4()]

            result = await _create_observation_directly(
                conn=conn,
                memory_engine=memory,
                bank_id=bank_id,
                source_memory_ids=dead_ids,
                observation_text="Should never land",
            )
            assert result == {"action": "skipped", "reason": "sources_deleted"}

            assert await _count_orphan_observations(conn, bank_id) == 0
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM memory_units WHERE bank_id = $1 AND fact_type = 'observation'",
                bank_id,
            )
            assert row["n"] == 0, "No observation row should have been inserted"

        await memory.delete_bank(bank_id, request_context=request_context)

    @pytest.mark.asyncio
    async def test_create_proceeds_with_subset_of_live_sources(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        """When some sources are dead and some are live, the create proceeds
        but the observation references only the live ids."""
        bank_id = f"test-orphan-create-mixed-{uuid.uuid4().hex[:8]}"
        await _ensure_bank(memory, bank_id, request_context)

        pool = await memory._get_pool()
        async with pool.acquire() as conn:
            live = await _insert_memory(conn, bank_id, "still here")
            dead = uuid.uuid4()

            result = await _create_observation_directly(
                conn=conn,
                memory_engine=memory,
                bank_id=bank_id,
                source_memory_ids=[live, dead],
                observation_text="Mixed sources",
            )
            assert result.get("action") != "skipped"

            obs_row = await conn.fetchrow(
                "SELECT source_memory_ids FROM memory_units "
                "WHERE bank_id = $1 AND fact_type = 'observation'",
                bank_id,
            )
            assert obs_row is not None
            assert list(obs_row["source_memory_ids"]) == [live]

            assert await _count_orphan_observations(conn, bank_id) == 0

        await memory.delete_bank(bank_id, request_context=request_context)


# ---------------------------------------------------------------------------
# Integration: _execute_update_action with all-dead new sources
# ---------------------------------------------------------------------------


class TestUpdateObservationWithDeletedSources:
    @pytest.mark.asyncio
    async def test_update_skipped_when_all_new_sources_dead(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        bank_id = f"test-orphan-update-skip-{uuid.uuid4().hex[:8]}"
        await _ensure_bank(memory, bank_id, request_context)

        pool = await memory._get_pool()
        async with pool.acquire() as conn:
            existing_source = await _insert_memory(conn, bank_id, "alpha")
            obs_id = await _insert_observation(conn, bank_id, "old text", [existing_source])

            # Only fields touched before the early-return matter; the helper
            # short-circuits on the live-sources check immediately after looking
            # up the observation by id.
            existing_obs = MemoryFact(
                id=str(obs_id),
                text="old text",
                fact_type="observation",
                source_fact_ids=[str(existing_source)],
                tags=[],
            )

            dead_new_sources = [uuid.uuid4(), uuid.uuid4()]
            await _execute_update_action(
                conn=conn,
                memory_engine=memory,
                bank_id=bank_id,
                source_memory_ids=dead_new_sources,
                observation_id=str(obs_id),
                new_text="proposed new text",
                observations=[existing_obs],
            )

            row = await conn.fetchrow(
                "SELECT text, source_memory_ids FROM memory_units WHERE id = $1",
                obs_id,
            )
            assert row["text"] == "old text", "Update must be skipped when new sources are all dead"
            assert list(row["source_memory_ids"]) == [existing_source]

            assert await _count_orphan_observations(conn, bank_id) == 0

        await memory.delete_bank(bank_id, request_context=request_context)


# ---------------------------------------------------------------------------
# Invariant: orphan observations must not exist after any delete-path call
# ---------------------------------------------------------------------------


class TestOrphanInvariantAfterDeletes:
    @pytest.mark.asyncio
    async def test_delete_memory_unit_leaves_no_orphans(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        bank_id = f"test-orphan-inv-unit-{uuid.uuid4().hex[:8]}"
        await _ensure_bank(memory, bank_id, request_context)

        pool = await memory._get_pool()
        async with pool.acquire() as conn:
            m1 = await _insert_memory(conn, bank_id, "alpha")
            m2 = await _insert_memory(conn, bank_id, "beta")
            await _insert_observation(conn, bank_id, "obs", [m1, m2])

        await memory.delete_memory_unit(str(m1), request_context=request_context)

        async with pool.acquire() as conn:
            assert await _count_orphan_observations(conn, bank_id) == 0

        await memory.delete_bank(bank_id, request_context=request_context)

    @pytest.mark.asyncio
    async def test_delete_bank_with_fact_type_leaves_no_orphans(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        bank_id = f"test-orphan-inv-bank-{uuid.uuid4().hex[:8]}"
        await _ensure_bank(memory, bank_id, request_context)

        pool = await memory._get_pool()
        async with pool.acquire() as conn:
            m1 = await _insert_memory(conn, bank_id, "alpha", fact_type="experience")
            m2 = await _insert_memory(conn, bank_id, "beta", fact_type="experience")
            await _insert_observation(conn, bank_id, "obs", [m1, m2])

        await memory.delete_bank(bank_id, fact_type="experience", request_context=request_context)

        async with pool.acquire() as conn:
            assert await _count_orphan_observations(conn, bank_id) == 0

        await memory.delete_bank(bank_id, request_context=request_context)
