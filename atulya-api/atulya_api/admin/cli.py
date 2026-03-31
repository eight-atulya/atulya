"""
Atulya Admin CLI - backup and restore operations.
"""

import asyncio
import io
import json
import logging
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg
import typer

from ..config import AtulyaConfig
from ..engine.temporal import TimelineTemporalMetadata, classify_fact_temporal_metadata, normalize_datetime
from ..pg0 import parse_pg0_url, resolve_database_url


def _fq_table(table: str, schema: str) -> str:
    """Get fully-qualified table name with schema prefix."""
    return f"{schema}.{table}"


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger(__name__)

app = typer.Typer(name="atulya-admin", help="Atulya administrative commands")

# Tables to backup/restore in dependency order
# Import must happen in this order due to foreign key constraints
BACKUP_TABLES = [
    "banks",
    "documents",
    "entities",
    "chunks",
    "memory_units",
    "unit_entities",
    "entity_cooccurrences",
    "memory_links",
]

MANIFEST_VERSION = "1"


async def _backup(database_url: str, output_path: Path, schema: str = "public") -> dict[str, Any]:
    """Backup all tables to a zip file using binary COPY protocol."""
    conn = await asyncpg.connect(database_url)
    try:
        tables: dict[str, Any] = {}
        manifest: dict[str, Any] = {
            "version": MANIFEST_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "schema": schema,
            "tables": tables,
        }

        # Use a transaction with REPEATABLE READ isolation to get a consistent
        # snapshot across all tables. This prevents race conditions where
        # entity_cooccurrences could reference entities created after the
        # entities table was backed up.
        async with conn.transaction(isolation="repeatable_read"):
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, table in enumerate(BACKUP_TABLES, 1):
                    typer.echo(f"  [{i}/{len(BACKUP_TABLES)}] Backing up {table}...", nl=False)

                    buffer = io.BytesIO()

                    # Use binary COPY for exact type preservation
                    # asyncpg requires schema_name as separate parameter
                    await conn.copy_from_table(table, schema_name=schema, output=buffer, format="binary")

                    data = buffer.getvalue()
                    zf.writestr(f"{table}.bin", data)

                    # Get row count for manifest
                    qualified_table = _fq_table(table, schema)
                    row_count = await conn.fetchval(f"SELECT COUNT(*) FROM {qualified_table}")
                    tables[table] = {
                        "rows": row_count,
                        "size_bytes": len(data),
                    }

                    typer.echo(f" {row_count} rows")

                zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        return manifest
    finally:
        await conn.close()


async def _restore(database_url: str, input_path: Path, schema: str = "public") -> dict[str, Any]:
    """Restore all tables from a zip file using binary COPY protocol."""
    conn = await asyncpg.connect(database_url)
    try:
        with zipfile.ZipFile(input_path, "r") as zf:
            # Read and validate manifest
            manifest: dict[str, Any] = json.loads(zf.read("manifest.json"))
            if manifest.get("version") != MANIFEST_VERSION:
                raise ValueError(f"Unsupported backup version: {manifest.get('version')}")

            # Use a transaction for atomic restore - either all tables are
            # restored or none are, preventing partial/inconsistent state.
            async with conn.transaction():
                typer.echo("  Clearing existing data...")
                # Truncate tables in reverse order (respects FK constraints)
                for table in reversed(BACKUP_TABLES):
                    qualified_table = _fq_table(table, schema)
                    await conn.execute(f"TRUNCATE TABLE {qualified_table} CASCADE")

                # Restore tables in forward order
                for i, table in enumerate(BACKUP_TABLES, 1):
                    filename = f"{table}.bin"
                    if filename not in zf.namelist():
                        typer.echo(f"  [{i}/{len(BACKUP_TABLES)}] {table}: skipped (not in backup)")
                        continue

                    expected_rows = manifest["tables"].get(table, {}).get("rows", "?")
                    typer.echo(f"  [{i}/{len(BACKUP_TABLES)}] Restoring {table}... {expected_rows} rows")

                    data = zf.read(filename)
                    buffer = io.BytesIO(data)
                    # asyncpg requires schema_name as separate parameter
                    await conn.copy_to_table(table, schema_name=schema, source=buffer, format="binary")

                # Refresh materialized view
                typer.echo("  Refreshing materialized views...")
                await conn.execute(f"REFRESH MATERIALIZED VIEW {_fq_table('memory_units_bm25', schema)}")

        return manifest
    finally:
        await conn.close()


async def _run_backup(db_url: str, output: Path, schema: str = "public") -> dict[str, Any]:
    """Resolve database URL and run backup."""
    is_pg0, instance_name, _ = parse_pg0_url(db_url)
    if is_pg0:
        typer.echo(f"Starting embedded PostgreSQL (instance: {instance_name})...")
    resolved_url = await resolve_database_url(db_url)
    return await _backup(resolved_url, output, schema)


async def _run_restore(db_url: str, input_file: Path, schema: str = "public") -> dict[str, Any]:
    """Resolve database URL and run restore."""
    is_pg0, instance_name, _ = parse_pg0_url(db_url)
    if is_pg0:
        typer.echo(f"Starting embedded PostgreSQL (instance: {instance_name})...")
    resolved_url = await resolve_database_url(db_url)
    return await _restore(resolved_url, input_file, schema)


@app.command()
def backup(
    output: Path = typer.Argument(..., help="Output file path (.zip)"),
    schema: str = typer.Option("public", "--schema", "-s", help="Database schema to backup"),
):
    """Backup the Atulya database to a zip file."""
    config = AtulyaConfig.from_env()

    if not config.database_url:
        typer.echo("Error: Database URL not configured.", err=True)
        typer.echo("Set ATULYA_API_DATABASE_URL environment variable.", err=True)
        raise typer.Exit(1)

    if output.suffix != ".zip":
        output = output.with_suffix(".zip")

    typer.echo(f"Backing up database (schema: {schema}) to {output}...")

    manifest = asyncio.run(_run_backup(config.database_url, output, schema))

    total_rows = sum(t["rows"] for t in manifest["tables"].values())
    typer.echo(f"Backed up {total_rows} rows across {len(BACKUP_TABLES)} tables")
    typer.echo(f"Backup saved to {output}")


@app.command()
def restore(
    input_file: Path = typer.Argument(..., help="Input backup file (.zip)"),
    schema: str = typer.Option("public", "--schema", "-s", help="Database schema to restore to"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Restore the database from a backup file. WARNING: This deletes all existing data."""
    config = AtulyaConfig.from_env()

    if not config.database_url:
        typer.echo("Error: Database URL not configured.", err=True)
        typer.echo("Set ATULYA_API_DATABASE_URL environment variable.", err=True)
        raise typer.Exit(1)

    if not input_file.exists():
        typer.echo(f"Error: File not found: {input_file}", err=True)
        raise typer.Exit(1)

    if not yes:
        typer.confirm(
            "This will DELETE all existing data and replace it with the backup. Continue?",
            abort=True,
        )

    typer.echo(f"Restoring database (schema: {schema}) from {input_file}...")

    manifest = asyncio.run(_run_restore(config.database_url, input_file, schema))

    total_rows = sum(t["rows"] for t in manifest["tables"].values())
    typer.echo(f"Restored {total_rows} rows across {len(BACKUP_TABLES)} tables")
    typer.echo("Restore complete")


async def _run_migration(db_url: str, schema: str = "public") -> None:
    """Resolve database URL and run migrations."""
    from ..migrations import run_migrations

    is_pg0, instance_name, _ = parse_pg0_url(db_url)
    if is_pg0:
        typer.echo(f"Starting embedded PostgreSQL (instance: {instance_name})...")
    resolved_url = await resolve_database_url(db_url)
    run_migrations(resolved_url, schema=schema)


def _is_default_timeline_state(row: asyncpg.Record) -> bool:
    return (
        row["timeline_anchor_at"] is None
        and row["timeline_anchor_kind"] == "recorded_only"
        and row["temporal_direction"] == "atemporal"
        and row["temporal_confidence"] is None
        and row["temporal_reference_text"] is None
    )


def _derive_timeline_backfill_metadata(row: asyncpg.Record) -> TimelineTemporalMetadata:
    return classify_fact_temporal_metadata(
        fact_text=row["text"] or "",
        occurred_start=row["occurred_start"],
        mentioned_at=row["mentioned_at"],
        created_at=row["created_at"],
        explicit_temporal=row["occurred_start"] is not None,
        inferred_temporal=False,
        fact_kind="conversation",
    )


def _timeline_metadata_changed(row: asyncpg.Record, metadata: TimelineTemporalMetadata) -> bool:
    return any(
        [
            normalize_datetime(row["timeline_anchor_at"]) != normalize_datetime(metadata.anchor_at),
            row["timeline_anchor_kind"] != metadata.anchor_kind,
            row["temporal_direction"] != metadata.direction,
            row["temporal_confidence"] != metadata.confidence,
            row["temporal_reference_text"] != metadata.reference_text,
        ]
    )


async def _backfill_timeline_metadata(
    db_url: str,
    *,
    schema: str = "public",
    batch_size: int = 500,
    bank_id: str | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
) -> dict[str, int]:
    """Backfill timeline metadata in batches without touching core memory columns."""
    is_pg0, instance_name, _ = parse_pg0_url(db_url)
    if is_pg0:
        typer.echo(f"Starting embedded PostgreSQL (instance: {instance_name})...")
    resolved_url = await resolve_database_url(db_url)

    conn = await asyncpg.connect(resolved_url)
    try:
        table = _fq_table("memory_units", schema)
        scanned = 0
        updated = 0
        cursor_created_at: datetime | None = None
        cursor_id: uuid.UUID | None = None

        while True:
            rows = await conn.fetch(
                f"""
                SELECT id, bank_id, text, fact_type, occurred_start, mentioned_at, created_at,
                       timeline_anchor_at, timeline_anchor_kind, temporal_direction,
                       temporal_confidence, temporal_reference_text
                FROM {table}
                WHERE ($1::text IS NULL OR bank_id = $1)
                  AND (
                    ($2::timestamptz IS NULL AND $3::uuid IS NULL)
                    OR created_at > $2
                    OR (created_at = $2 AND id > $3)
                  )
                ORDER BY created_at ASC, id ASC
                LIMIT $4
                """,
                bank_id,
                cursor_created_at,
                cursor_id,
                batch_size,
            )
            if not rows:
                break

            updates: list[tuple[datetime | None, str, str, float | None, str | None, uuid.UUID]] = []
            for row in rows:
                scanned += 1
                if not overwrite and not _is_default_timeline_state(row):
                    continue

                metadata = _derive_timeline_backfill_metadata(row)
                if not _timeline_metadata_changed(row, metadata):
                    continue

                updates.append(
                    (
                        metadata.anchor_at,
                        metadata.anchor_kind,
                        metadata.direction,
                        metadata.confidence,
                        metadata.reference_text,
                        row["id"],
                    )
                )

            if updates:
                updated += len(updates)
                if not dry_run:
                    await conn.executemany(
                        f"""
                        UPDATE {table}
                        SET timeline_anchor_at = $1,
                            timeline_anchor_kind = $2,
                            temporal_direction = $3,
                            temporal_confidence = $4,
                            temporal_reference_text = $5
                        WHERE id = $6
                        """,
                        updates,
                    )

            last_row = rows[-1]
            cursor_created_at = last_row["created_at"]
            cursor_id = last_row["id"]

        return {"scanned": scanned, "updated": updated}
    finally:
        await conn.close()


@app.command(name="run-db-migration")
def run_db_migration(
    schema: str = typer.Option("public", "--schema", "-s", help="Database schema to run migrations on"),
):
    """Run database migrations to the latest version."""
    config = AtulyaConfig.from_env()

    if not config.database_url:
        typer.echo("Error: Database URL not configured.", err=True)
        typer.echo("Set ATULYA_API_DATABASE_URL environment variable.", err=True)
        raise typer.Exit(1)

    typer.echo(f"Running database migrations (schema: {schema})...")

    asyncio.run(_run_migration(config.database_url, schema))

    typer.echo("Database migrations completed successfully")


async def _decommission_worker(db_url: str, worker_id: str, schema: str = "public") -> int:
    """Release all tasks owned by a worker, setting them back to pending status."""
    is_pg0, instance_name, _ = parse_pg0_url(db_url)
    if is_pg0:
        typer.echo(f"Starting embedded PostgreSQL (instance: {instance_name})...")
    resolved_url = await resolve_database_url(db_url)

    conn = await asyncpg.connect(resolved_url)
    try:
        table = _fq_table("async_operations", schema)
        result = await conn.fetch(
            f"""
            UPDATE {table}
            SET status = 'pending', worker_id = NULL, claimed_at = NULL, updated_at = now()
            WHERE worker_id = $1 AND status = 'processing'
            RETURNING operation_id
            """,
            worker_id,
        )
        return len(result)
    finally:
        await conn.close()


@app.command(name="decommission-worker")
def decommission_worker(
    worker_id: str = typer.Argument(..., help="Worker ID to decommission"),
    schema: str = typer.Option("public", "--schema", "-s", help="Database schema"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Release all tasks owned by a worker (sets status back to pending).

    Use this command when a worker has crashed or been removed without graceful shutdown.
    All tasks that were being processed by the worker will be released back to the queue
    so other workers can pick them up.
    """
    config = AtulyaConfig.from_env()

    if not config.database_url:
        typer.echo("Error: Database URL not configured.", err=True)
        typer.echo("Set ATULYA_API_DATABASE_URL environment variable.", err=True)
        raise typer.Exit(1)

    if not yes:
        typer.confirm(
            f"This will release all tasks owned by worker '{worker_id}' back to pending. Continue?",
            abort=True,
        )

    typer.echo(f"Decommissioning worker '{worker_id}' (schema: {schema})...")

    count = asyncio.run(_decommission_worker(config.database_url, worker_id, schema))

    if count > 0:
        typer.echo(f"Released {count} task(s) from worker '{worker_id}'")
    else:
        typer.echo(f"No tasks found for worker '{worker_id}'")


@app.command(name="backfill-timeline-metadata")
def backfill_timeline_metadata(
    schema: str = typer.Option("public", "--schema", "-s", help="Database schema"),
    batch_size: int = typer.Option(500, "--batch-size", min=1, help="Rows to process per batch"),
    bank_id: str | None = typer.Option(None, "--bank-id", help="Only backfill a single bank"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Calculate updates without writing"),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Recompute timeline metadata even for rows that already appear populated",
    ),
):
    """Backfill timeline metadata for historical memory units."""
    config = AtulyaConfig.from_env()

    if not config.database_url:
        typer.echo("Error: Database URL not configured.", err=True)
        typer.echo("Set ATULYA_API_DATABASE_URL environment variable.", err=True)
        raise typer.Exit(1)

    target = f"bank '{bank_id}'" if bank_id else "all banks"
    typer.echo(
        f"Backfilling timeline metadata for {target} (schema: {schema}, batch_size: {batch_size}, dry_run: {dry_run})..."
    )

    result = asyncio.run(
        _backfill_timeline_metadata(
            config.database_url,
            schema=schema,
            batch_size=batch_size,
            bank_id=bank_id,
            dry_run=dry_run,
            overwrite=overwrite,
        )
    )

    typer.echo(f"Scanned {result['scanned']} memory units")
    typer.echo(f"{'Would update' if dry_run else 'Updated'} {result['updated']} memory units")


def main():
    app()


if __name__ == "__main__":
    main()
