"""
Webhook registration lookup and delivery queueing.

Purpose:
    Match fired domain events to registered webhooks (env-global and per-bank DB
    rows) and enqueue ``webhook_delivery`` tasks on ``async_operations`` for
    the worker to HTTP POST (via ``MemoryEngine._handle_webhook_delivery``).

Trigger path:
    - ``MemoryEngine`` after retain/consolidation completion (and similar flows).
    - ``fire_event``: standalone pool acquire (post-commit delivery).
    - ``fire_event_with_conn``: same transaction as the triggering write
      (transactional outbox — delivery row rolls back if parent txn aborts).

Inputs:
    - ``WebhookEvent``: ``event``, ``bank_id``, ``operation_id``, ``status``,
      ``timestamp``, typed ``data`` payload.
    - ``global_webhooks``: parsed from env at engine init.
    - ``schema``: tenant schema for ``webhooks`` and ``async_operations`` tables.

Outputs:
    - One ``async_operations`` INSERT per matched webhook (pending,
      ``operation_type='webhook_delivery'``).
    - Debug/error logs; no synchronous HTTP from this module.

Side effects:
    - PostgreSQL writes only; actual HTTP is deferred to workers.
    - ``fire_event`` swallows queueing errors (primary operation already committed).
    - ``fire_event_with_conn`` re-raises on failure (aborts enclosing txn).

Mutability:
    - Read-only on webhook config; creates new operation rows and UUIDs per match.

Impact radius:
    - Customer integrations listening for ``retain.completed`` /
      ``consolidation.completed``.
    - Retry schedule (``RETRY_DELAYS``) is consumed downstream in delivery handler,
      not here.

Core logic:
    Load enabled webhooks where ``bank_id = event.bank_id OR bank_id IS NULL``,
    filter by ``event_types``, serialize payload once, enqueue delivery tasks.

Failure modes:
    - DB errors in ``fire_event``: logged, event may be lost (no outbox).
    - DB errors in ``fire_event_with_conn``: txn aborted — caller must retry all.

Maintenance notes:
    Good: add a new ``WebhookEventType`` and fire it from the completing operation
    using ``fire_event_with_conn`` inside the success transaction.
    Bad: perform synchronous HTTP here — would block retain/consolidation and
    bypass worker retry/backoff semantics.
"""

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import asyncpg

from .models import WebhookConfig, WebhookEvent, WebhookHttpConfig

if TYPE_CHECKING:
    from atulya_api.extensions.tenant import TenantExtension

logger = logging.getLogger(__name__)

# Retry delay schedule in seconds: 5 retries after the first attempt.
# Fast early retries catch transient failures; later retries handle longer outages.
RETRY_DELAYS = [5, 300, 1800, 7200, 18000]
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1  # first attempt + len(RETRY_DELAYS) retries


def _fq_table(table: str, schema: str | None = None) -> str:
    """Get fully-qualified table name with optional schema prefix."""
    if schema:
        return f'"{schema}".{table}'
    return table


def _parse_http_config(value: str | dict | None) -> WebhookHttpConfig:
    """Parse http_config column value (JSONB returned as text or dict) into a model."""
    if value is None:
        return WebhookHttpConfig()
    if isinstance(value, str):
        return WebhookHttpConfig.model_validate_json(value)
    return WebhookHttpConfig.model_validate(value)


class WebhookManager:
    """
    Queues webhook deliveries as async worker tasks.

    Purpose:
        Bridge domain events to outbound HTTP without blocking the dataplane.

    Trigger path:
        Constructed on ``MemoryEngine`` init; ``fire_event*`` called from engine
        completion paths.

    Inputs:
        ``asyncpg.Pool``, env ``global_webhooks``, optional ``TenantExtension``.

    Side effects:
        Inserts into ``async_operations``; HMAC signing happens at delivery time
        in the worker handler, not here.

    Maintenance notes:
        Global webhooks are prepended to DB rows — duplicate URLs may receive
        multiple deliveries if registered both globally and per-bank.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        global_webhooks: list[WebhookConfig],
        tenant_extension: "TenantExtension | None" = None,
    ):
        self._pool = pool
        self._global_webhooks = global_webhooks
        self._tenant_extension = tenant_extension

    def _sign_payload(self, secret: str, payload_bytes: bytes) -> str:
        """Compute HMAC-SHA256 signature for a payload."""
        return "sha256=" + hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()

    async def fire_event(self, event: WebhookEvent, schema: str | None = None) -> None:
        """
        Queue webhook deliveries for an event as async_operations tasks.

        Loads per-bank and global webhooks, inserts pending webhook_delivery tasks for
        any webhook whose event_types list matches the fired event type. The worker
        poller picks these up and calls MemoryEngine._handle_webhook_delivery().

        Args:
            event: The event to deliver.
            schema: Database schema (for multi-tenant). None = default schema.
        """
        webhook_table = _fq_table("webhooks", schema)
        ops_table = _fq_table("async_operations", schema)
        now = datetime.now(timezone.utc)
        payload_str = event.model_dump_json()

        try:
            # Load per-bank webhooks from DB (bank-specific + global NULL rows)
            rows = await self._pool.fetch(
                f"""
                SELECT id, bank_id, url, secret, event_types, enabled, http_config::text
                FROM {webhook_table}
                WHERE (bank_id = $1 OR bank_id IS NULL) AND enabled = true
                """,
                event.bank_id,
            )

            db_webhooks = [
                WebhookConfig(
                    id=str(row["id"]),
                    bank_id=row["bank_id"],
                    url=row["url"],
                    secret=row["secret"],
                    event_types=list(row["event_types"]) if row["event_types"] else [],
                    enabled=row["enabled"],
                    http_config=_parse_http_config(row["http_config"]),
                )
                for row in rows
            ]

            # Merge with global webhooks from env config
            all_webhooks = self._global_webhooks + db_webhooks
            matched = 0

            for webhook in all_webhooks:
                if not webhook.enabled:
                    continue
                if event.event.value not in webhook.event_types:
                    continue

                operation_id = uuid.uuid4()
                webhook_id = webhook.id if webhook.id else None

                task_payload = json.dumps(
                    {
                        "type": "webhook_delivery",
                        "operation_id": str(operation_id),
                        "bank_id": event.bank_id,
                        "url": webhook.url,
                        "secret": webhook.secret,
                        "event_type": event.event.value,
                        "payload": payload_str,
                        "webhook_id": webhook_id,
                        "http_config": webhook.http_config.model_dump(),
                    }
                )

                await self._pool.execute(
                    f"""
                    INSERT INTO {ops_table}
                      (operation_id, bank_id, operation_type, status, task_payload, result_metadata, created_at, updated_at)
                    VALUES ($1, $2, 'webhook_delivery', 'pending', $3::jsonb, '{{}}'::jsonb, $4, $4)
                    """,
                    operation_id,
                    event.bank_id,
                    task_payload,
                    now,
                )
                matched += 1

            logger.debug(f"Fired webhook event {event.event} for bank {event.bank_id}: {matched} delivery(ies) queued")

        except Exception as e:
            logger.error(f"Failed to queue webhook deliveries for event {event.event}: {e}")

    async def fire_event_with_conn(
        self, event: WebhookEvent, conn: asyncpg.Connection, schema: str | None = None
    ) -> None:
        """
        Queue webhook deliveries within an existing database connection/transaction.

        Identical to fire_event() but uses the provided connection instead of acquiring
        one from the pool. Use this to atomically insert delivery tasks in the same
        transaction as the primary operation (transactional outbox pattern).

        Args:
            event: The event to deliver.
            conn: Existing asyncpg connection (may be inside an active transaction).
            schema: Database schema (for multi-tenant). None = default schema.
        """
        webhook_table = _fq_table("webhooks", schema)
        ops_table = _fq_table("async_operations", schema)
        now = datetime.now(timezone.utc)
        payload_str = event.model_dump_json()

        try:
            rows = await conn.fetch(
                f"""
                SELECT id, bank_id, url, secret, event_types, enabled, http_config::text
                FROM {webhook_table}
                WHERE (bank_id = $1 OR bank_id IS NULL) AND enabled = true
                """,
                event.bank_id,
            )

            db_webhooks = [
                WebhookConfig(
                    id=str(row["id"]),
                    bank_id=row["bank_id"],
                    url=row["url"],
                    secret=row["secret"],
                    event_types=list(row["event_types"]) if row["event_types"] else [],
                    enabled=row["enabled"],
                    http_config=_parse_http_config(row["http_config"]),
                )
                for row in rows
            ]

            all_webhooks = self._global_webhooks + db_webhooks
            matched = 0

            for webhook in all_webhooks:
                if not webhook.enabled:
                    continue
                if event.event.value not in webhook.event_types:
                    continue

                operation_id = uuid.uuid4()
                webhook_id = webhook.id if webhook.id else None

                task_payload = json.dumps(
                    {
                        "type": "webhook_delivery",
                        "operation_id": str(operation_id),
                        "bank_id": event.bank_id,
                        "url": webhook.url,
                        "secret": webhook.secret,
                        "event_type": event.event.value,
                        "payload": payload_str,
                        "webhook_id": webhook_id,
                        "http_config": webhook.http_config.model_dump(),
                    }
                )

                await conn.execute(
                    f"""
                    INSERT INTO {ops_table}
                      (operation_id, bank_id, operation_type, status, task_payload, result_metadata, created_at, updated_at)
                    VALUES ($1, $2, 'webhook_delivery', 'pending', $3::jsonb, '{{}}'::jsonb, $4, $4)
                    """,
                    operation_id,
                    event.bank_id,
                    task_payload,
                    now,
                )
                matched += 1

            logger.debug(
                f"Fired webhook event {event.event} for bank {event.bank_id}: {matched} delivery(ies) queued (in-transaction)"
            )

        except Exception as e:
            logger.error(
                f"Failed to queue webhook deliveries (in-transaction) for event {event.event}: {e}. "
                "CRITICAL: The enclosing database transaction is now aborted and will roll back all changes."
            )
            raise
