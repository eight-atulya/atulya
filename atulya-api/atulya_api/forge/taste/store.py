"""Database persistence for Taste Studio.

Purpose
    CRUD and lineage operations for ``forge_taste_datasets``, ``forge_taste_sets``,
    and ``forge_transform_chains`` tables. Maps asyncpg rows to Pydantic models.

Trigger path
    Called exclusively from ``forge/taste/engine.py``, ``retain.py``, and
    transform handlers — not directly from HTTP routes.

Inputs
    - ``MemoryEngine`` for connection pool (``_get_pool``) and tenant schema
      via ``fq_table``.
    - UUID string IDs, JSON payloads validated upstream or via ``validation``.

Outputs
    - ``TasteDataset``, ``TasteSet``, ``TasteTransformChain`` models.
    - Paginated dict for ``list_sets`` (``sets``, ``total``, ``limit``, ``offset``).

Side effects
    - INSERT/UPDATE/DELETE on forge taste tables within bank tenant schema.
    - ``import_sets`` and ``create_variant_sets`` run in transactions.
    - ``revert_set`` clears transform log, retain linkage, and resets working copy.

Mutability
    - ``source_payload`` is set at import/variant creation and not updated by
      transforms (only ``working_payload`` changes).
    - ``transform_log`` is append-only via ``append_transform_log``; revert
      resets it to empty.
    - Status lifecycle: ``draft`` → ``ready`` (manual) → ``retained`` (after
      retain) or back to ``draft`` on revert.

Impact radius
    - All Taste Studio UI data, export materialization, and retain linkage
      (``memory_unit_ids``, ``entity_ids`` on sets).
    - Dataset ``updated_at`` bumped on set mutations for list ordering.

Core logic
    - Row mappers coerce JSONB/text columns into typed Pydantic structures.
    - Import assigns sequential ``set_key`` values with optional prefix.
    - Variants share ``set_key`` with parent but increment ``variant_index``.

Failure modes
    - Invalid UUIDs raise ``TasteNotFoundError`` (intentionally vague message).
    - Missing rows on delete/update raise ``TasteNotFoundError``.
    - Payload validation on ``update_set`` delegates to ``validate_payload_for_schema``.

Maintenance notes
    - Good: add columns with matching changes to ``_row_to_*`` mappers and models.
    - Bad: delete datasets without CASCADE awareness — FK behavior depends on
      migration definitions; verify schema before adding hard deletes.
    - ``LIST_SETS_PAGE_SIZE`` caps page size; ``list_all_sets`` paginates internally.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from atulya_api.engine.db_utils import acquire_with_retry
from atulya_api.engine.memory_engine import fq_table

from .errors import TasteNotFoundError, TasteValidationError
from .models import (
    TasteDataset,
    TasteSet,
    TasteSetStatus,
    TasteTransformChain,
    TransformLogEntry,
    TransformOpSpec,
)
from .validation import parse_import_sets, validate_payload_for_schema

if TYPE_CHECKING:
    from atulya_api.engine.memory_engine import MemoryEngine

LIST_SETS_PAGE_SIZE = 500


def _parse_uuid(value: str, *, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise TasteNotFoundError(f"{label} not found: {value}") from exc


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_dataset(row: Any, *, set_count: int = 0) -> TasteDataset:
    return TasteDataset(
        id=str(row["id"]),
        bank_id=row["bank_id"],
        name=row["name"],
        description=row["description"],
        schema_type=row["schema_type"],
        taste_tags=list(row["taste_tags"] or []),
        taste_profile_json=row["taste_profile_json"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        set_count=set_count,
    )


def _coerce_json_obj(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return dict(value)


def _coerce_json_array(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    return list(value)


def _parse_transform_log(raw: Any) -> list[TransformLogEntry]:
    entries: list[TransformLogEntry] = []
    for item in _coerce_json_array(raw):
        if isinstance(item, dict):
            entries.append(TransformLogEntry.model_validate(item))
    return entries


def _row_to_set(row: Any) -> TasteSet:
    return TasteSet(
        id=str(row["id"]),
        dataset_id=str(row["dataset_id"]),
        bank_id=row["bank_id"],
        set_key=row["set_key"],
        parent_set_id=str(row["parent_set_id"]) if row["parent_set_id"] else None,
        variant_index=int(row["variant_index"] or 0),
        source_payload=_coerce_json_obj(row["source_payload"]),
        working_payload=_coerce_json_obj(row["working_payload"]),
        transform_log=_parse_transform_log(row["transform_log"]),
        taste_tags=list(row["taste_tags"] or []),
        entity_ids=list(row["entity_ids"] or []),
        memory_unit_ids=list(row["memory_unit_ids"] or []),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_chain(row: Any) -> TasteTransformChain:
    ops_raw = row["ops"] or []
    ops = [TransformOpSpec.model_validate(op) for op in ops_raw if isinstance(op, dict)]
    return TasteTransformChain(
        id=str(row["id"]),
        bank_id=row["bank_id"],
        name=row["name"],
        ops=ops,
        is_default=bool(row["is_default"]),
        created_at=row["created_at"],
    )


async def _get_dataset_row(conn: Any, bank_id: str, dataset_id: str) -> Any:
    row = await conn.fetchrow(
        f"""
        SELECT id, bank_id, name, description, schema_type, taste_tags, taste_profile_json, created_at, updated_at
        FROM {fq_table("forge_taste_datasets")}
        WHERE bank_id = $1 AND id = $2
        """,
        bank_id,
        _parse_uuid(dataset_id, label="Dataset"),
    )
    if not row:
        raise TasteNotFoundError(f"Dataset not found: {dataset_id}")
    return row


async def list_datasets(memory_engine: "MemoryEngine", bank_id: str) -> list[TasteDataset]:
    """List datasets for a bank with aggregated ``set_count`` per dataset."""
    pool = await memory_engine._get_pool()
    async with acquire_with_retry(pool) as conn:
        rows = await conn.fetch(
            f"""
            SELECT d.id, d.bank_id, d.name, d.description, d.schema_type, d.taste_tags,
                   d.taste_profile_json, d.created_at, d.updated_at,
                   COUNT(s.id) AS set_count
            FROM {fq_table("forge_taste_datasets")} d
            LEFT JOIN {fq_table("forge_taste_sets")} s ON s.dataset_id = d.id
            WHERE d.bank_id = $1
            GROUP BY d.id
            ORDER BY d.updated_at DESC
            """,
            bank_id,
        )
    return [_row_to_dataset(row, set_count=int(row["set_count"] or 0)) for row in rows]


async def create_dataset(
    memory_engine: "MemoryEngine",
    bank_id: str,
    *,
    name: str,
    description: str | None,
    schema_type: str,
    taste_tags: list[str],
) -> TasteDataset:
    """Insert a new taste dataset; sets start empty."""
    pool = await memory_engine._get_pool()
    now = _utcnow()
    async with acquire_with_retry(pool) as conn:
        row = await conn.fetchrow(
            f"""
            INSERT INTO {fq_table("forge_taste_datasets")}
                (bank_id, name, description, schema_type, taste_tags, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $6)
            RETURNING id, bank_id, name, description, schema_type, taste_tags, taste_profile_json, created_at, updated_at
            """,
            bank_id,
            name,
            description,
            schema_type,
            taste_tags,
            now,
        )
    return _row_to_dataset(row)


async def get_dataset(memory_engine: "MemoryEngine", bank_id: str, dataset_id: str) -> TasteDataset:
    pool = await memory_engine._get_pool()
    dataset_uuid = _parse_uuid(dataset_id, label="Dataset")
    async with acquire_with_retry(pool) as conn:
        row = await _get_dataset_row(conn, bank_id, dataset_id)
        count_row = await conn.fetchrow(
            f"SELECT COUNT(*) AS c FROM {fq_table('forge_taste_sets')} WHERE dataset_id = $1",
            dataset_uuid,
        )
    return _row_to_dataset(row, set_count=int(count_row["c"] if count_row else 0))


async def update_dataset(
    memory_engine: "MemoryEngine",
    bank_id: str,
    dataset_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    taste_tags: list[str] | None = None,
    taste_profile_json: dict[str, Any] | None = None,
) -> TasteDataset:
    pool = await memory_engine._get_pool()
    dataset_uuid = _parse_uuid(dataset_id, label="Dataset")
    async with acquire_with_retry(pool) as conn:
        await _get_dataset_row(conn, bank_id, dataset_id)
        row = await conn.fetchrow(
            f"""
            UPDATE {fq_table("forge_taste_datasets")}
            SET
                name = COALESCE($3, name),
                description = COALESCE($4, description),
                taste_tags = COALESCE($5, taste_tags),
                taste_profile_json = COALESCE($6::jsonb, taste_profile_json),
                updated_at = $7
            WHERE bank_id = $1 AND id = $2
            RETURNING id, bank_id, name, description, schema_type, taste_tags, taste_profile_json, created_at, updated_at
            """,
            bank_id,
            dataset_uuid,
            name,
            description,
            taste_tags,
            json.dumps(taste_profile_json) if taste_profile_json is not None else None,
            _utcnow(),
        )
        count_row = await conn.fetchrow(
            f"SELECT COUNT(*) AS c FROM {fq_table('forge_taste_sets')} WHERE dataset_id = $1",
            dataset_uuid,
        )
    return _row_to_dataset(row, set_count=int(count_row["c"] if count_row else 0))


async def delete_dataset(memory_engine: "MemoryEngine", bank_id: str, dataset_id: str) -> None:
    pool = await memory_engine._get_pool()
    dataset_uuid = _parse_uuid(dataset_id, label="Dataset")
    async with acquire_with_retry(pool) as conn:
        result = await conn.execute(
            f"DELETE FROM {fq_table('forge_taste_datasets')} WHERE bank_id = $1 AND id = $2",
            bank_id,
            dataset_uuid,
        )
    if result == "DELETE 0":
        raise TasteNotFoundError(f"Dataset not found: {dataset_id}")


async def list_sets(
    memory_engine: "MemoryEngine",
    bank_id: str,
    dataset_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    page_limit = min(max(limit, 1), LIST_SETS_PAGE_SIZE)
    pool = await memory_engine._get_pool()
    dataset_uuid = _parse_uuid(dataset_id, label="Dataset")
    async with acquire_with_retry(pool) as conn:
        await _get_dataset_row(conn, bank_id, dataset_id)
        rows = await conn.fetch(
            f"""
            SELECT id, dataset_id, bank_id, set_key, parent_set_id, variant_index,
                   source_payload, working_payload, transform_log, taste_tags,
                   entity_ids, memory_unit_ids, status, created_at, updated_at
            FROM {fq_table("forge_taste_sets")}
            WHERE bank_id = $1 AND dataset_id = $2
            ORDER BY set_key ASC, variant_index ASC
            LIMIT $3 OFFSET $4
            """,
            bank_id,
            dataset_uuid,
            page_limit,
            offset,
        )
        count_row = await conn.fetchrow(
            f"SELECT COUNT(*) AS total FROM {fq_table('forge_taste_sets')} WHERE bank_id = $1 AND dataset_id = $2",
            bank_id,
            dataset_uuid,
        )
    return {
        "sets": [_row_to_set(row).model_dump(mode="json") for row in rows],
        "total": int(count_row["total"] if count_row else 0),
        "limit": page_limit,
        "offset": offset,
    }


async def list_all_sets(
    memory_engine: "MemoryEngine",
    bank_id: str,
    dataset_id: str,
) -> list[TasteSet]:
    """Load every set in a dataset using paginated list_sets."""
    all_sets: list[TasteSet] = []
    offset = 0
    while True:
        page = await list_sets(memory_engine, bank_id, dataset_id, limit=LIST_SETS_PAGE_SIZE, offset=offset)
        for item in page["sets"]:
            all_sets.append(TasteSet.model_validate(item))
        total = int(page["total"])
        offset += LIST_SETS_PAGE_SIZE
        if offset >= total:
            break
    return all_sets


async def get_set(memory_engine: "MemoryEngine", bank_id: str, set_id: str) -> TasteSet:
    pool = await memory_engine._get_pool()
    set_uuid = _parse_uuid(set_id, label="Set")
    async with acquire_with_retry(pool) as conn:
        row = await conn.fetchrow(
            f"""
            SELECT id, dataset_id, bank_id, set_key, parent_set_id, variant_index,
                   source_payload, working_payload, transform_log, taste_tags,
                   entity_ids, memory_unit_ids, status, created_at, updated_at
            FROM {fq_table("forge_taste_sets")}
            WHERE bank_id = $1 AND id = $2
            """,
            bank_id,
            set_uuid,
        )
    if not row:
        raise TasteNotFoundError(f"Set not found: {set_id}")
    return _row_to_set(row)


async def get_sets_by_ids(memory_engine: "MemoryEngine", bank_id: str, set_ids: list[str]) -> list[TasteSet]:
    if not set_ids:
        return []
    pool = await memory_engine._get_pool()
    uuids = [_parse_uuid(sid, label="Set") for sid in set_ids]
    async with acquire_with_retry(pool) as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, dataset_id, bank_id, set_key, parent_set_id, variant_index,
                   source_payload, working_payload, transform_log, taste_tags,
                   entity_ids, memory_unit_ids, status, created_at, updated_at
            FROM {fq_table("forge_taste_sets")}
            WHERE bank_id = $1 AND id = ANY($2::uuid[])
            ORDER BY set_key ASC, variant_index ASC
            """,
            bank_id,
            uuids,
        )
    return [_row_to_set(row) for row in rows]


async def import_sets(
    memory_engine: "MemoryEngine",
    bank_id: str,
    dataset_id: str,
    *,
    sets: list[dict[str, Any]] | None = None,
    jsonl: str | None = None,
    taste_tags: list[str] | None = None,
    set_key_prefix: str | None = None,
) -> list[TasteSet]:
    """Bulk-import sets; both ``source_payload`` and ``working_payload`` start identical."""
    pool = await memory_engine._get_pool()
    dataset_uuid = _parse_uuid(dataset_id, label="Dataset")
    async with acquire_with_retry(pool) as conn:
        dataset_row = await _get_dataset_row(conn, bank_id, dataset_id)
        schema_type = dataset_row["schema_type"]
        payloads = parse_import_sets(schema_type=schema_type, sets=sets, jsonl=jsonl)
        dataset_tags = list(dataset_row["taste_tags"] or [])
        merged_tags = dataset_tags + list(taste_tags or [])
        prefix = set_key_prefix or "set"
        count_row = await conn.fetchrow(
            f"SELECT COUNT(*) AS c FROM {fq_table('forge_taste_sets')} WHERE dataset_id = $1",
            dataset_uuid,
        )
        start_idx = int(count_row["c"] if count_row else 0) + 1
        created: list[TasteSet] = []
        now = _utcnow()
        async with conn.transaction():
            for offset, payload in enumerate(payloads):
                set_key = f"{prefix}_{start_idx + offset:04d}"
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO {fq_table("forge_taste_sets")}
                        (dataset_id, bank_id, set_key, variant_index, source_payload, working_payload,
                         taste_tags, status, created_at, updated_at)
                    VALUES ($1, $2, $3, 0, $4::jsonb, $4::jsonb, $5, 'draft', $6, $6)
                    RETURNING id, dataset_id, bank_id, set_key, parent_set_id, variant_index,
                              source_payload, working_payload, transform_log, taste_tags,
                              entity_ids, memory_unit_ids, status, created_at, updated_at
                    """,
                    dataset_uuid,
                    bank_id,
                    set_key,
                    json.dumps(payload),
                    merged_tags,
                    now,
                )
                created.append(_row_to_set(row))
            await conn.execute(
                f"UPDATE {fq_table('forge_taste_datasets')} SET updated_at = $2 WHERE id = $1",
                dataset_uuid,
                now,
            )
    return created


async def update_set(
    memory_engine: "MemoryEngine",
    bank_id: str,
    set_id: str,
    *,
    working_payload: dict[str, Any] | None = None,
    taste_tags: list[str] | None = None,
    status: TasteSetStatus | None = None,
) -> TasteSet:
    pool = await memory_engine._get_pool()
    set_uuid = _parse_uuid(set_id, label="Set")
    async with acquire_with_retry(pool) as conn:
        existing = await conn.fetchrow(
            f"""
            SELECT s.id, s.dataset_id, d.schema_type
            FROM {fq_table("forge_taste_sets")} s
            JOIN {fq_table("forge_taste_datasets")} d ON d.id = s.dataset_id
            WHERE s.bank_id = $1 AND s.id = $2
            """,
            bank_id,
            set_uuid,
        )
        if not existing:
            raise TasteNotFoundError(f"Set not found: {set_id}")
        if working_payload is not None:
            validate_payload_for_schema(working_payload, existing["schema_type"])
        row = await conn.fetchrow(
            f"""
            UPDATE {fq_table("forge_taste_sets")}
            SET
                working_payload = COALESCE($3::jsonb, working_payload),
                taste_tags = COALESCE($4, taste_tags),
                status = COALESCE($5, status),
                updated_at = $6
            WHERE bank_id = $1 AND id = $2
            RETURNING id, dataset_id, bank_id, set_key, parent_set_id, variant_index,
                      source_payload, working_payload, transform_log, taste_tags,
                      entity_ids, memory_unit_ids, status, created_at, updated_at
            """,
            bank_id,
            set_uuid,
            json.dumps(working_payload) if working_payload is not None else None,
            taste_tags,
            status,
            _utcnow(),
        )
        await conn.execute(
            f"UPDATE {fq_table('forge_taste_datasets')} SET updated_at = $2 WHERE id = $1",
            existing["dataset_id"],
            _utcnow(),
        )
    return _row_to_set(row)


async def revert_set(memory_engine: "MemoryEngine", bank_id: str, set_id: str) -> TasteSet:
    """Reset working copy to source, clear transform log and retain linkage."""
    pool = await memory_engine._get_pool()
    set_uuid = _parse_uuid(set_id, label="Set")
    async with acquire_with_retry(pool) as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE {fq_table("forge_taste_sets")}
            SET
                working_payload = source_payload,
                status = 'draft',
                memory_unit_ids = '{{}}',
                entity_ids = '{{}}',
                transform_log = '[]'::jsonb,
                updated_at = $3
            WHERE bank_id = $1 AND id = $2
            RETURNING id, dataset_id, bank_id, set_key, parent_set_id, variant_index,
                      source_payload, working_payload, transform_log, taste_tags,
                      entity_ids, memory_unit_ids, status, created_at, updated_at
            """,
            bank_id,
            set_uuid,
            _utcnow(),
        )
    if not row:
        raise TasteNotFoundError(f"Set not found: {set_id}")
    return _row_to_set(row)


async def append_transform_log(
    memory_engine: "MemoryEngine",
    bank_id: str,
    set_id: str,
    *,
    entry: TransformLogEntry,
    working_payload: dict[str, Any],
) -> TasteSet:
    """Atomically append one transform audit entry and update working payload."""
    pool = await memory_engine._get_pool()
    set_uuid = _parse_uuid(set_id, label="Set")
    async with acquire_with_retry(pool) as conn:
        existing = await conn.fetchrow(
            f"""
            SELECT transform_log
            FROM {fq_table("forge_taste_sets")}
            WHERE bank_id = $1 AND id = $2
            """,
            bank_id,
            set_uuid,
        )
        if not existing:
            raise TasteNotFoundError(f"Set not found: {set_id}")
        log_items = _coerce_json_array(existing["transform_log"])
        log_items.append(entry.model_dump(mode="json"))
        row = await conn.fetchrow(
            f"""
            UPDATE {fq_table("forge_taste_sets")}
            SET
                working_payload = $3::jsonb,
                transform_log = $4::jsonb,
                updated_at = $5
            WHERE bank_id = $1 AND id = $2
            RETURNING id, dataset_id, bank_id, set_key, parent_set_id, variant_index,
                      source_payload, working_payload, transform_log, taste_tags,
                      entity_ids, memory_unit_ids, status, created_at, updated_at
            """,
            bank_id,
            set_uuid,
            json.dumps(working_payload),
            json.dumps(log_items),
            _utcnow(),
        )
    if not row:
        raise TasteNotFoundError(f"Set not found: {set_id}")
    return _row_to_set(row)


async def create_variant_sets(
    memory_engine: "MemoryEngine",
    bank_id: str,
    parent: TasteSet,
    *,
    variants: list[dict[str, Any]],
) -> list[TasteSet]:
    """Insert child variant rows sharing parent's ``set_key`` with incremented index."""
    pool = await memory_engine._get_pool()
    created: list[TasteSet] = []
    now = _utcnow()
    async with acquire_with_retry(pool) as conn:
        max_variant = await conn.fetchval(
            f"""
            SELECT COALESCE(MAX(variant_index), 0)
            FROM {fq_table("forge_taste_sets")}
            WHERE dataset_id = $1 AND set_key = $2
            """,
            uuid.UUID(parent.dataset_id),
            parent.set_key,
        )
        next_index = int(max_variant or 0)
        for payload in variants:
            next_index += 1
            row = await conn.fetchrow(
                f"""
                INSERT INTO {fq_table("forge_taste_sets")}
                    (dataset_id, bank_id, set_key, parent_set_id, variant_index,
                     source_payload, working_payload, taste_tags, status, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, 'draft', $9, $9)
                RETURNING id, dataset_id, bank_id, set_key, parent_set_id, variant_index,
                          source_payload, working_payload, transform_log, taste_tags,
                          entity_ids, memory_unit_ids, status, created_at, updated_at
                """,
                uuid.UUID(parent.dataset_id),
                bank_id,
                parent.set_key,
                uuid.UUID(parent.id),
                next_index,
                json.dumps(parent.source_payload),
                json.dumps(payload),
                parent.taste_tags,
                now,
            )
            created.append(_row_to_set(row))
        await conn.execute(
            f"UPDATE {fq_table('forge_taste_datasets')} SET updated_at = $2 WHERE id = $1",
            uuid.UUID(parent.dataset_id),
            now,
        )
    return created


async def update_set_after_retain(
    memory_engine: "MemoryEngine",
    bank_id: str,
    set_id: str,
    *,
    memory_unit_ids: list[str],
    entity_ids: list[str] | None = None,
) -> TasteSet:
    """Link retained memory units to a set and mark status ``retained``."""
    pool = await memory_engine._get_pool()
    set_uuid = _parse_uuid(set_id, label="Set")
    async with acquire_with_retry(pool) as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE {fq_table("forge_taste_sets")}
            SET
                memory_unit_ids = $3,
                entity_ids = COALESCE($4, entity_ids),
                status = 'retained',
                updated_at = $5
            WHERE bank_id = $1 AND id = $2
            RETURNING id, dataset_id, bank_id, set_key, parent_set_id, variant_index,
                      source_payload, working_payload, transform_log, taste_tags,
                      entity_ids, memory_unit_ids, status, created_at, updated_at
            """,
            bank_id,
            set_uuid,
            memory_unit_ids,
            entity_ids,
            _utcnow(),
        )
    if not row:
        raise TasteNotFoundError(f"Set not found: {set_id}")
    return _row_to_set(row)


async def list_transform_chains(memory_engine: "MemoryEngine", bank_id: str) -> list[TasteTransformChain]:
    pool = await memory_engine._get_pool()
    async with acquire_with_retry(pool) as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, bank_id, name, ops, is_default, created_at
            FROM {fq_table("forge_transform_chains")}
            WHERE bank_id = $1
            ORDER BY is_default DESC, created_at DESC
            """,
            bank_id,
        )
    return [_row_to_chain(row) for row in rows]


async def get_transform_chain(memory_engine: "MemoryEngine", bank_id: str, chain_id: str) -> TasteTransformChain:
    pool = await memory_engine._get_pool()
    chain_uuid = _parse_uuid(chain_id, label="Transform chain")
    async with acquire_with_retry(pool) as conn:
        row = await conn.fetchrow(
            f"""
            SELECT id, bank_id, name, ops, is_default, created_at
            FROM {fq_table("forge_transform_chains")}
            WHERE bank_id = $1 AND id = $2
            """,
            bank_id,
            chain_uuid,
        )
    if not row:
        raise TasteNotFoundError(f"Transform chain not found: {chain_id}")
    return _row_to_chain(row)
