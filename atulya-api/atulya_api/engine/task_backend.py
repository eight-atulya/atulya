"""
Task backend for distributed async operation execution.

Purpose:
    Abstracts how background work is queued and (optionally) executed. The API
    submits task dicts; workers poll ``async_operations`` and call
    ``MemoryEngine.execute_task`` to run them.

Trigger path:
    - ``MemoryEngine`` selects a backend at init based on ``worker_enabled`` and
      test/embedded mode (see ``MemoryEngine._init_task_backend``).
    - HTTP handlers and engine methods call ``submit_task`` after creating or
      updating ``async_operations`` rows (retain, reflect, consolidation, etc.).
    - ``WorkerPoller`` (separate process/module) claims rows and invokes the
      registered executor; ``SyncTaskBackend`` executes inline in-process.

Inputs:
    - ``task_dict``: JSON-serializable dict with at least ``type``; often
      ``operation_id``, ``bank_id``, and operation-specific payload fields.
    - ``pool_getter`` / ``schema`` / ``schema_getter``: tenant routing for
      ``BrokerTaskBackend``.
    - Executor callback: async ``(task_dict) -> None``, typically
      ``MemoryEngine.execute_task``.

Outputs:
    - ``BrokerTaskBackend``: INSERT/UPDATE on ``async_operations.task_payload``.
    - ``SyncTaskBackend``: direct executor invocation; no queue row required
      when ``operation_id`` is absent.
    - Returns are always ``None``; outcomes are persisted by the executor.

Side effects:
    - PostgreSQL writes to ``async_operations`` (broker mode).
    - In-process task execution (sync mode or when executor is registered).
    - Error logging on executor failures; no automatic retry at this layer.

Mutability:
    - ``TaskBackend._executor`` and ``_initialized`` are set at runtime.
    - ``task_dict`` is serialized to JSON; callers should treat it as immutable
      after submit (workers read the stored payload).

Impact radius:
    - All async features: retain batches, reflect, consolidation, webhooks,
      access-count updates, dream runs, etc.
    - Changing publish semantics (``task_payload IS NULL`` guard) can corrupt
      in-flight operations or duplicate work.
    - Schema resolution must stay aligned with ``WorkerPoller`` and
      ``WebhookManager``.

Core logic:
    - Broker: publish-once semantics — UPDATE only when ``task_payload IS NULL``;
      otherwise INSERT a new pending operation.
    - Sync: ``submit_task`` immediately calls ``_execute_task``.

Failure modes:
    - Missing executor: task is logged and skipped (broker still stores payload).
    - Non-JSON-serializable task fields: ``json.dumps`` raises before DB write.
    - Executor exceptions: logged with traceback; worker layer handles retries.

Maintenance notes:
    Good: add a new ``type`` value and handler in ``execute_task`` without
    changing backend interfaces.
    Bad: remove the ``task_payload IS NULL`` guard or bypass ``async_operations``
    for operations that workers expect to claim.
"""

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)


def fq_table(table: str, schema: str | None = None) -> str:
    """Get fully-qualified table name with optional schema prefix."""
    if schema:
        return f'"{schema}".{table}'
    return table


class TaskBackend(ABC):
    """
    Abstract base for task queue backends.

    Purpose:
        Define the contract for publishing task dicts and optionally executing
        them in-process when an executor is registered.

    Trigger path:
        Subclassed by ``SyncTaskBackend`` and ``BrokerTaskBackend``; wired from
        ``MemoryEngine`` during engine initialization.

    Inputs:
        Executor callback set via ``set_executor`` before worker/poller use.

    Outputs / side effects:
        Subclasses implement ``submit_task`` (queue or run) and ``shutdown``.

    Mutability:
        ``_executor`` and ``_initialized`` are instance state mutated at runtime.

    Impact radius:
        Any change to this interface affects both API submission and test sync
        execution paths.

    Maintenance notes:
        Keep task dicts JSON-serializable; datetime handling is only in
        ``BrokerTaskBackend.submit_task`` via ``datetime_encoder``.
    """

    def __init__(self):
        """Initialize the task backend."""
        self._executor: Callable[[dict[str, Any]], Awaitable[None]] | None = None
        self._initialized = False

    def set_executor(self, executor: Callable[[dict[str, Any]], Awaitable[None]]):
        """
        Set the executor callback for processing tasks.

        Args:
            executor: Async function that takes a task dict and executes it
        """
        self._executor = executor

    @abstractmethod
    async def initialize(self):
        """
        Initialize the backend (e.g., connect to database).
        """
        pass

    @abstractmethod
    async def submit_task(self, task_dict: dict[str, Any]):
        """
        Submit a task for execution.

        Args:
            task_dict: Task as a dictionary (must be serializable)
        """
        pass

    @abstractmethod
    async def shutdown(self):
        """
        Shutdown the backend gracefully.
        """
        pass

    async def _execute_task(self, task_dict: dict[str, Any]):
        """
        Execute a task through the registered executor.

        Args:
            task_dict: Task dictionary to execute
        """
        if self._executor is None:
            task_type = task_dict.get("type", "unknown")
            logger.warning(f"No executor registered, skipping task {task_type}")
            return

        try:
            await self._executor(task_dict)
        except Exception as e:
            task_type = task_dict.get("type", "unknown")
            logger.error(f"Error executing task {task_type}: {e}")
            import traceback

            traceback.print_exc()


class SyncTaskBackend(TaskBackend):
    """
    In-process task backend for tests and embedded mode.

    Purpose:
        Execute tasks immediately on ``submit_task`` without writing to
        ``async_operations`` (unless the executor itself does).

    Trigger path:
        Selected when ``worker_enabled`` is false or in isolated test setups.

    Side effects:
        Runs executor synchronously in the caller's async context.

    Failure modes:
        Executor exceptions propagate to the ``submit_task`` caller.

    Maintenance notes:
        Do not use in production multi-worker deployments; there is no
        cross-process queue or claim semantics.
    """

    async def initialize(self):
        """No-op for sync backend."""
        self._initialized = True
        logger.debug("SyncTaskBackend initialized")

    async def submit_task(self, task_dict: dict[str, Any]):
        """
        Execute the task immediately (synchronously).

        Args:
            task_dict: Task dictionary to execute
        """
        if not self._initialized:
            await self.initialize()

        await self._execute_task(task_dict)

    async def shutdown(self):
        """No-op for sync backend."""
        self._initialized = False
        logger.debug("SyncTaskBackend shutdown")


class BrokerTaskBackend(TaskBackend):
    """
    PostgreSQL-backed task publish backend (production default).

    Purpose:
        Persist ``task_payload`` on ``async_operations`` rows for ``WorkerPoller``
        to claim with ``FOR UPDATE SKIP LOCKED``.

    Trigger path:
        API ``MemoryEngine`` when background workers are enabled.

    Inputs:
        ``pool_getter``, static ``schema``, or dynamic ``schema_getter`` for
        multi-tenant table qualification.

    Side effects:
        INSERT or conditional UPDATE on ``async_operations``; does not execute
        tasks itself (except via separately registered executor in tests).

    Core logic:
        Publish-once UPDATE when ``operation_id`` is present; INSERT when absent.

    Impact radius:
        Worker fairness, webhook delivery ordering, and async operation status
        all depend on consistent payload publication.

    Maintenance notes:
        Good: pass ``operation_id`` from the row created by the HTTP handler so
        publish and claim share one operation record.
        Bad: overwrite ``task_payload`` after a worker claim — the NULL guard
        exists specifically to prevent that race.
    """

    def __init__(
        self,
        pool_getter: Callable[[], "asyncpg.Pool"],
        schema: str | None = None,
        schema_getter: Callable[[], str | None] | None = None,
    ):
        """
        Initialize the broker task backend.

        Args:
            pool_getter: Callable that returns the asyncpg connection pool
            schema: Database schema for multi-tenant support (optional, static)
            schema_getter: Callable that returns current schema dynamically (optional).
                          If set, takes precedence over static schema for submit_task.
        """
        super().__init__()
        self._pool_getter = pool_getter
        self._schema = schema
        self._schema_getter = schema_getter

    async def initialize(self):
        """Initialize the backend."""
        self._initialized = True
        logger.info("BrokerTaskBackend initialized")

    async def submit_task(self, task_dict: dict[str, Any]):
        """
        Store task payload in async_operations table.

        The task_dict should contain an 'operation_id' if updating an existing
        operation record, otherwise a new operation will be created.

        Args:
            task_dict: Task dictionary to store (must be JSON serializable)
        """
        if not self._initialized:
            await self.initialize()

        pool = self._pool_getter()
        operation_id = task_dict.get("operation_id")
        task_type = task_dict.get("type", "unknown")
        bank_id = task_dict.get("bank_id")

        # Custom encoder to handle datetime objects
        from datetime import datetime

        def datetime_encoder(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

        payload_json = json.dumps(task_dict, default=datetime_encoder)

        schema = self._schema_getter() if self._schema_getter else self._schema
        table = fq_table("async_operations", schema)

        if operation_id:
            # Publish step: only set task_payload if it hasn't been set already.
            # Without the `AND task_payload IS NULL` guard, a late retry of the
            # submitter could overwrite a payload that's already been claimed
            # and is mid-execution by a worker, corrupting the operation. The
            # claim is the source of truth; submit is publish-once.
            result = await pool.execute(
                f"""
                UPDATE {table}
                SET task_payload = $1::jsonb, updated_at = now()
                WHERE operation_id = $2 AND task_payload IS NULL
                """,
                payload_json,
                operation_id,
            )
            # asyncpg returns "UPDATE n" — extract the rowcount for logging.
            try:
                rowcount = int(result.split()[-1]) if isinstance(result, str) else 0
            except (ValueError, AttributeError):
                rowcount = 0
            if rowcount == 0:
                logger.debug(
                    f"Skipped publish for operation {operation_id}: payload already set (task likely already claimed)"
                )
            else:
                logger.debug(f"Published task payload for operation {operation_id} (rowcount={rowcount})")
        else:
            # Insert new operation (for tasks without pre-created records)
            # e.g., access_count_update tasks
            import uuid

            new_id = uuid.uuid4()
            await pool.execute(
                f"""
                INSERT INTO {table} (operation_id, bank_id, operation_type, status, task_payload)
                VALUES ($1, $2, $3, 'pending', $4::jsonb)
                """,
                new_id,
                bank_id,
                task_type,
                payload_json,
            )
            logger.debug(f"Created new operation {new_id} for task type {task_type}")

    async def shutdown(self):
        """Shutdown the backend."""
        self._initialized = False
        logger.info("BrokerTaskBackend shutdown")

    async def wait_for_pending_tasks(self, timeout: float = 120.0):
        """
        Wait for pending tasks to be processed.

        In the broker model, this polls the database to check if tasks
        for this process have been completed. This is useful in tests
        when worker_enabled=True (API processes its own tasks).

        Args:
            timeout: Maximum time to wait in seconds
        """
        import asyncio

        pool = self._pool_getter()
        schema = self._schema_getter() if self._schema_getter else self._schema
        table = fq_table("async_operations", schema)

        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            # Check if there are any pending tasks with payloads
            count = await pool.fetchval(
                f"""
                SELECT COUNT(*) FROM {table}
                WHERE status = 'pending' AND task_payload IS NOT NULL
                """
            )

            if count == 0:
                return

            await asyncio.sleep(0.5)

        logger.warning(f"Timeout waiting for pending tasks after {timeout}s")
