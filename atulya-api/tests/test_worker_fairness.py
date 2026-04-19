"""
Regression tests for Group 4 of the hindsight bugfix backport: worker
fairness, consolidation slot reservation, and idempotent ``submit_task``.

Three independent issues, all in the same surface (worker poller +
task_backend):

1. ``submit_task`` UPDATE clobbered ``task_payload`` for already-claimed
   rows, corrupting in-flight executions on a late retry of the submitter.
2. Consolidation slots were a *ceiling* not a *reservation*: under heavy
   retain load the standard pool would saturate ``max_slots`` and
   consolidation tasks would never get scheduled.
3. ``claim_batch`` walked schemas in deterministic order, so a single
   heavy tenant could fill every slot before the next tenant was even
   inspected — small tenants starved indefinitely.

These tests pin the contract for each fix.
"""

import asyncio
import json
import uuid

import pytest
import pytest_asyncio

from atulya_api.engine.task_backend import BrokerTaskBackend
from atulya_api.worker.poller import WorkerPoller

pytestmark = pytest.mark.xdist_group("worker_tests")


@pytest_asyncio.fixture
async def pool(pg0_db_url):
    import asyncpg

    from atulya_api.pg0 import resolve_database_url

    resolved_url = await resolve_database_url(pg0_db_url)
    pool = await asyncpg.create_pool(resolved_url, min_size=2, max_size=10, command_timeout=30)
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def clean_operations(pool):
    await pool.execute("DELETE FROM async_operations WHERE bank_id LIKE 'test-fair-%'")
    yield
    await pool.execute("DELETE FROM async_operations WHERE bank_id LIKE 'test-fair-%'")


# ---------------------------------------------------------------------------
# submit_task idempotency
# ---------------------------------------------------------------------------


class TestSubmitTaskIdempotency:
    @pytest.mark.asyncio
    async def test_submit_task_does_not_clobber_already_set_payload(self, pool, clean_operations):
        """A second submit_task for an operation whose payload was already
        published (e.g. row was claimed by a worker mid-retry) must NOT
        overwrite the in-flight payload.
        """
        op_id = uuid.uuid4()
        bank_id = f"test-fair-{uuid.uuid4().hex[:8]}"

        original_payload = {"type": "test_task", "version": "v1-original"}
        await pool.execute(
            """
            INSERT INTO async_operations (operation_id, bank_id, operation_type, status, task_payload)
            VALUES ($1, $2, 'test', 'processing', $3::jsonb)
            """,
            op_id,
            bank_id,
            json.dumps(original_payload),
        )

        backend = BrokerTaskBackend(pool_getter=lambda: pool)
        await backend.initialize()

        # Late-arriving submitter retry tries to publish a NEW payload for
        # the SAME operation_id. Must be a no-op because the payload is set.
        later_payload = {
            "operation_id": str(op_id),
            "type": "test_task",
            "bank_id": bank_id,
            "version": "v2-clobber-attempt",
        }
        await backend.submit_task(later_payload)

        row = await pool.fetchrow(
            "SELECT task_payload FROM async_operations WHERE operation_id = $1",
            op_id,
        )
        stored = json.loads(row["task_payload"])
        assert stored["version"] == "v1-original", (
            "submit_task must NOT overwrite a payload that has already been published; "
            "doing so corrupts in-flight task executions"
        )

    @pytest.mark.asyncio
    async def test_submit_task_publishes_when_payload_is_null(self, pool, clean_operations):
        """The first submit_task call (or any call where task_payload IS
        NULL) must populate the payload — that's the publish step.
        """
        op_id = uuid.uuid4()
        bank_id = f"test-fair-{uuid.uuid4().hex[:8]}"

        await pool.execute(
            """
            INSERT INTO async_operations (operation_id, bank_id, operation_type, status)
            VALUES ($1, $2, 'test', 'pending')
            """,
            op_id,
            bank_id,
        )

        backend = BrokerTaskBackend(pool_getter=lambda: pool)
        await backend.initialize()

        payload = {
            "operation_id": str(op_id),
            "type": "test_task",
            "bank_id": bank_id,
            "version": "v1",
        }
        await backend.submit_task(payload)

        row = await pool.fetchrow(
            "SELECT task_payload FROM async_operations WHERE operation_id = $1",
            op_id,
        )
        stored = json.loads(row["task_payload"])
        assert stored["version"] == "v1"


# ---------------------------------------------------------------------------
# Consolidation slot reservation
# ---------------------------------------------------------------------------


class TestConsolidationSlotReservation:
    @pytest.mark.asyncio
    async def test_consolidation_slot_reserved_under_standard_load(self, pool, clean_operations):
        """When the standard pool is fully loaded, consolidation slots must
        still be available — they are reserved, not a ceiling.
        """
        bank_id = f"test-fair-{uuid.uuid4().hex[:8]}"

        # 5 standard 'retain' tasks
        for _ in range(5):
            op_id = uuid.uuid4()
            await pool.execute(
                """
                INSERT INTO async_operations (operation_id, bank_id, operation_type, status, task_payload)
                VALUES ($1, $2, 'retain', 'pending', $3::jsonb)
                """,
                op_id,
                bank_id,
                json.dumps({"type": "test", "operation_type": "retain", "bank_id": bank_id}),
            )

        # 1 consolidation task for the same bank
        cons_id = uuid.uuid4()
        await pool.execute(
            """
            INSERT INTO async_operations (operation_id, bank_id, operation_type, status, task_payload)
            VALUES ($1, $2, 'consolidation', 'pending', $3::jsonb)
            """,
            cons_id,
            bank_id,
            json.dumps({"type": "test", "operation_type": "consolidation", "bank_id": bank_id}),
        )

        # max_slots=5 with consolidation reserved=2, sub_routine reserved=0
        # → standard pool = max(0, 5-2-0) = 3.
        # Consolidation must be claimed even though there are 5 standard tasks
        # competing for the standard pool.
        poller = WorkerPoller(
            pool=pool,
            worker_id="test-worker-reserve",
            executor=lambda x: None,
            max_slots=5,
            consolidation_max_slots=2,
            sub_routine_max_slots=0,
        )

        claimed = await poller.claim_batch()
        op_types = [t.task_dict.get("operation_type") for t in claimed]
        assert op_types.count("consolidation") == 1, (
            f"Consolidation slot must be reserved even under standard load; got {op_types}"
        )
        # Standard pool budget is 3, but rotation pass 1 takes 1 standard +
        # 1 consolidation, then pass 2 backfills up to the standard cap.
        assert op_types.count("retain") <= 3
        assert len(claimed) <= 5

    @pytest.mark.asyncio
    async def test_standard_cannot_consume_consolidation_slots(self, pool, clean_operations):
        """Standard tasks must never claim more than their reserved budget
        even if no consolidation tasks are pending.
        """
        bank_id = f"test-fair-{uuid.uuid4().hex[:8]}"
        for _ in range(10):
            op_id = uuid.uuid4()
            await pool.execute(
                """
                INSERT INTO async_operations (operation_id, bank_id, operation_type, status, task_payload)
                VALUES ($1, $2, 'retain', 'pending', $3::jsonb)
                """,
                op_id,
                bank_id,
                json.dumps({"type": "test", "operation_type": "retain", "bank_id": bank_id}),
            )

        # max_slots=5, consolidation reserved=2, sub_routine reserved=2
        # → standard pool = 1.
        poller = WorkerPoller(
            pool=pool,
            worker_id="test-worker-strict",
            executor=lambda x: None,
            max_slots=5,
            consolidation_max_slots=2,
            sub_routine_max_slots=2,
        )

        claimed = await poller.claim_batch()
        retain_claimed = sum(1 for t in claimed if t.task_dict.get("operation_type") == "retain")
        assert retain_claimed == 1, (
            f"Standard pool reserved budget is 1; got {retain_claimed} retain tasks claimed"
        )


# ---------------------------------------------------------------------------
# Per-tenant rotation
# ---------------------------------------------------------------------------


class _StaticTenantExtension:
    """Test double that returns a fixed list of tenant schemas."""

    def __init__(self, schemas: list[str | None]):
        self._schemas = schemas

    async def list_tenants(self):
        from types import SimpleNamespace

        return [SimpleNamespace(schema=s) for s in self._schemas]


class TestSchemaRotation:
    def test_next_schema_idx_starts_at_zero(self, pool):
        poller = WorkerPoller(
            pool=pool,
            worker_id="test-worker-rot",
            executor=lambda x: None,
        )
        assert poller._next_schema_idx == 0

    @pytest.mark.asyncio
    async def test_rotation_advances_by_one_each_call(self, pool, clean_operations):
        """Every call to claim_batch advances the rotation head by 1, even
        when no tasks are pending in the head schema.
        """
        # Use the default schema (None) only; rotation modulo 1 stays at 0,
        # but the index field still advances by 1 (which is what production
        # multi-tenant deployments depend on).
        poller = WorkerPoller(
            pool=pool,
            worker_id="test-worker-rot",
            executor=lambda x: None,
            tenant_extension=_StaticTenantExtension([None, "tenant_a", "tenant_b"]),
        )
        # Patch _claim_batch_for_schema to be a no-op so we only test the
        # rotation accounting, not the SQL.
        calls: list[str | None] = []

        async def noop_claim(schema, standard_limit, consolidation_limit, sub_routine_limit):
            calls.append(schema)
            return []

        poller._claim_batch_for_schema = noop_claim

        await poller.claim_batch()
        assert poller._next_schema_idx == 1
        await poller.claim_batch()
        assert poller._next_schema_idx == 2
        await poller.claim_batch()
        assert poller._next_schema_idx == 0  # wraps modulo 3

        # Each call visited every schema (once in pass 1, once in pass 2 = 6
        # total per call). Sanity-check that all schemas were visited at
        # least once across the three calls.
        assert {None, "tenant_a", "tenant_b"} <= set(calls)

    @pytest.mark.asyncio
    async def test_rotation_visits_all_schemas_in_one_cycle(self, pool, clean_operations):
        """In a single cycle, every schema in the rotation gets at least one
        claim_batch_for_schema call (even with capacity to spare elsewhere),
        so a small tenant cannot be starved indefinitely.
        """
        poller = WorkerPoller(
            pool=pool,
            worker_id="test-worker-rot2",
            executor=lambda x: None,
            tenant_extension=_StaticTenantExtension([None, "tenant_b", "tenant_c"]),
        )

        visited: list[str | None] = []

        async def noop_claim(schema, standard_limit, consolidation_limit, sub_routine_limit):
            visited.append(schema)
            return []

        poller._claim_batch_for_schema = noop_claim

        await poller.claim_batch()
        # Pass 1 alone covers every schema — small tenant served within one cycle.
        assert visited[: 3] == [None, "tenant_b", "tenant_c"]
