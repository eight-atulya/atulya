"""
Atulya Admin CLI - backup and restore operations.
"""

import asyncio
import io
import json
import logging
import os
import secrets
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg
import typer

from ..auth import fq, hash_password
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


def _new_secret(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(48)}"


@app.command(name="generate-auth-env")
def generate_auth_env(
    dataplane_url: str = typer.Option(
        "http://localhost:8888",
        "--dataplane-url",
        help="Control-plane URL for the atulya-api service.",
    ),
    api_port: int = typer.Option(8888, "--api-port", help="Local API port for the root .env block."),
    control_plane_port: int = typer.Option(9999, "--control-plane-port", help="Local UI port for the root .env block."),
    auth_schema: str = typer.Option("public", "--auth-schema", help="Schema that stores org/auth tables."),
    signup_mode: str = typer.Option(
        "public",
        "--signup-mode",
        help="Signup mode: disabled, bootstrap, or public.",
    ),
    environment: str = typer.Option(
        "development",
        "--environment",
        help="Runtime environment: development, staging, or production.",
    ),
):
    """Generate production-safe auth/admin environment values.

    Paste the root block into the repo-root .env. Paste the UI block into
    atulya-control-plane/.env.local only when starting Next.js directly from
    that package instead of using scripts/dev/start-control-plane.sh.
    """
    if signup_mode not in {"disabled", "bootstrap", "public"}:
        typer.echo("Error: --signup-mode must be disabled, bootstrap, or public.", err=True)
        raise typer.Exit(1)
    if environment not in {"development", "staging", "production"}:
        typer.echo("Error: --environment must be development, staging, or production.", err=True)
        raise typer.Exit(1)

    superuser_key = _new_secret("atulya_admin")
    key_hash_pepper = _new_secret("atulya_key_pepper")
    session_hash_pepper = _new_secret("atulya_session_pepper")

    typer.echo("# Repo-root .env")
    typer.echo(f"ATULYA_ENVIRONMENT={environment}")
    typer.echo("ATULYA_API_AUTH_MODE=database")
    typer.echo("ATULYA_API_ADMIN_ENABLED=true")
    typer.echo(f"ATULYA_API_SUPERUSER_KEY={superuser_key}")
    typer.echo(f"ATULYA_API_KEY_HASH_PEPPER={key_hash_pepper}")
    typer.echo(f"ATULYA_API_SESSION_HASH_PEPPER={session_hash_pepper}")
    typer.echo(f"ATULYA_API_AUTH_SCHEMA={auth_schema}")
    typer.echo(f"ATULYA_SIGNUP_MODE={signup_mode}")
    typer.echo("ATULYA_AUTH_EMAIL_VERIFICATION=required")
    typer.echo(f"ATULYA_AUTH_EMAIL_TRANSPORT={'smtp' if environment == 'production' else 'console'}")
    typer.echo(f"ATULYA_AUTH_PUBLIC_URL=http://localhost:{control_plane_port}")
    if environment == "production":
        typer.echo("ATULYA_AUTH_SMTP_HOST=")
        typer.echo("ATULYA_AUTH_SMTP_PORT=587")
        typer.echo("ATULYA_AUTH_SMTP_USERNAME=")
        typer.echo("ATULYA_AUTH_SMTP_PASSWORD=")
        typer.echo("ATULYA_AUTH_EMAIL_FROM=")
        typer.echo("ATULYA_AUTH_SMTP_STARTTLS=true")
    typer.echo(f"ATULYA_CP_COOKIE_SECURE={'true' if environment == 'production' else 'false'}")
    typer.echo(f"ATULYA_API_PORT={api_port}")
    typer.echo(f"ATULYA_CP_PORT={control_plane_port}")
    typer.echo(f"ATULYA_CP_DATAPLANE_API_URL={dataplane_url}")
    typer.echo("")
    typer.echo("# atulya-control-plane/.env.local, only if running Next.js directly")
    typer.echo(f"ATULYA_CP_DATAPLANE_API_URL={dataplane_url}")


async def _auth_connection() -> asyncpg.Connection:
    config = AtulyaConfig.from_env()
    if not config.database_url:
        raise RuntimeError("ATULYA_API_DATABASE_URL is not configured")
    return await asyncpg.connect(await resolve_database_url(config.database_url))


@app.command(name="create-platform-admin")
def create_platform_admin(
    email: str = typer.Option(..., "--email", prompt=True),
    name: str = typer.Option(..., "--name", prompt=True),
):
    """Create a verified human platform operator using an interactive password."""

    password = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    if len(password) < 12:
        typer.echo("Error: password must contain at least 12 characters.", err=True)
        raise typer.Exit(1)

    async def _create() -> None:
        connection = await _auth_connection()
        try:
            async with connection.transaction():
                normalized_email = email.strip().lower()
                if await connection.fetchval(
                    f"SELECT 1 FROM {fq('principals')} WHERE lower(email) = $1",
                    normalized_email,
                ):
                    raise RuntimeError("A global account already exists for this email")
                principal_id = uuid.uuid4()
                await connection.execute(
                    f"""
                    INSERT INTO {fq("principals")}
                        (id, email, display_name, principal_type, status, email_verified_at)
                    VALUES ($1, $2, $3, 'user', 'active', NOW())
                    """,
                    principal_id,
                    normalized_email,
                    name.strip(),
                )
                await connection.execute(
                    f"INSERT INTO {fq('principal_credentials')} (principal_id, password_hash) VALUES ($1, $2)",
                    principal_id,
                    hash_password(password),
                )
                await connection.execute(
                    f"""
                    INSERT INTO {fq("access_grants")}
                        (org_id, subject_type, subject_id, action, scope_type, scope_id)
                    VALUES (NULL, 'principal', $1, 'system.admin', 'system', '*')
                    """,
                    str(principal_id),
                )
                await connection.execute(
                    f"""
                    INSERT INTO {fq("audit_events")}
                        (actor_principal_id, action, target_type, target_id, metadata)
                    VALUES (NULL, 'platform.admin.create', 'principal', $1, $2)
                    """,
                    str(principal_id),
                    json.dumps({"source": "atulya-admin"}),
                )
            typer.echo(f"Created platform admin {normalized_email} ({principal_id})")
        finally:
            await connection.close()

    try:
        asyncio.run(_create())
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command(name="list-platform-admins")
def list_platform_admins():
    """List human identities holding the system administrator grant."""

    async def _list() -> None:
        connection = await _auth_connection()
        try:
            rows = await connection.fetch(
                f"""
                SELECT p.id::text, p.email, p.display_name, p.status, p.created_at::text
                FROM {fq("principals")} p
                JOIN {fq("access_grants")} g
                  ON g.subject_type = 'principal' AND g.subject_id = p.id::text
                WHERE g.org_id IS NULL AND g.action = 'system.admin'
                  AND g.scope_type = 'system' AND g.scope_id = '*'
                ORDER BY p.email
                """
            )
            if not rows:
                typer.echo("No platform administrators found.")
                return
            for row in rows:
                typer.echo(f"{row['email']}\t{row['display_name']}\t{row['status']}\t{row['id']}")
        finally:
            await connection.close()

    asyncio.run(_list())


@app.command(name="revoke-platform-admin")
def revoke_platform_admin(email: str = typer.Option(..., "--email", prompt=True)):
    """Remove platform access and revoke all sessions for an identity."""

    async def _revoke() -> None:
        connection = await _auth_connection()
        try:
            async with connection.transaction():
                principal_id = await connection.fetchval(
                    f"SELECT id FROM {fq('principals')} WHERE lower(email) = $1",
                    email.strip().lower(),
                )
                if not principal_id:
                    raise RuntimeError("Platform administrator not found")
                result = await connection.execute(
                    f"""
                    DELETE FROM {fq("access_grants")}
                    WHERE org_id IS NULL AND subject_type = 'principal' AND subject_id = $1
                      AND action = 'system.admin' AND scope_type = 'system' AND scope_id = '*'
                    """,
                    str(principal_id),
                )
                if result.endswith("0"):
                    raise RuntimeError("Identity does not hold platform access")
                await connection.execute(
                    f"""
                    UPDATE {fq("principal_sessions")}
                    SET revoked_at = NOW(), revocation_reason = 'platform_admin_revoked'
                    WHERE principal_id = $1 AND revoked_at IS NULL
                    """,
                    principal_id,
                )
                await connection.execute(
                    f"""
                    INSERT INTO {fq("audit_events")}
                        (actor_principal_id, action, target_type, target_id, metadata)
                    VALUES (NULL, 'platform.admin.revoke', 'principal', $1, $2)
                    """,
                    str(principal_id),
                    json.dumps({"source": "atulya-admin"}),
                )
            typer.echo(f"Revoked platform access for {email.strip().lower()}")
        finally:
            await connection.close()

    try:
        asyncio.run(_revoke())
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


RESET_CONFIRMATION = "RESET-ATULYA-AUTH-AND-BANKS"


@app.command(name="reset-development-auth-and-banks")
def reset_development_auth_and_banks(
    confirm: str = typer.Option("", "--confirm", help=f"Must equal {RESET_CONFIRMATION}."),
):
    """Destroy development auth, organization schemas, and memory-bank data."""

    if os.getenv("ATULYA_ENVIRONMENT", "development").strip().lower() == "production":
        typer.echo("Refusing to reset while ATULYA_ENVIRONMENT=production.", err=True)
        raise typer.Exit(1)

    async def _reset() -> None:
        connection = await _auth_connection()
        try:
            schemas = await connection.fetch(f"SELECT schema_name FROM {fq('orgs')} ORDER BY schema_name")
            auth_tables = (
                "audit_events",
                "auth_challenges",
                "auth_rate_limits",
                "access_grants",
                "api_keys",
                "principal_sessions",
                "principal_credentials",
                "membership_scopes",
                "org_memberships",
                "role_actions",
                "roles",
                "principals",
                "orgs",
            )
            typer.echo("Organization schemas to drop:")
            for row in schemas:
                typer.echo(f"  {row['schema_name']}")
            typer.echo("Auth tables to truncate:")
            for table in auth_tables:
                typer.echo(f"  {fq(table)}")
            typer.echo(f"Memory-bank root to truncate:\n  {fq('banks')}")
            if confirm != RESET_CONFIRMATION:
                raise RuntimeError(f"Pass --confirm {RESET_CONFIRMATION} to execute the reset")
            async with connection.transaction():
                for row in schemas:
                    schema_name = row["schema_name"]
                    if not schema_name.startswith("org_"):
                        raise RuntimeError(f"Refusing to drop unexpected schema {schema_name!r}")
                    await connection.execute(f'DROP SCHEMA "{schema_name}" CASCADE')
                tables = ", ".join(fq(table) for table in auth_tables)
                await connection.execute(f"TRUNCATE TABLE {tables} CASCADE")
                await connection.execute(f"TRUNCATE TABLE {fq('banks')} CASCADE")
            typer.echo("Development auth, organization schemas, and memory banks reset.")
        finally:
            await connection.close()

    try:
        asyncio.run(_reset())
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# Backup table manifest — complete ordered list of every user-data table.
#
# Rules:
#   1. Order is strict FK-dependency order (parent before child) so that
#      COPY-in during restore never violates a constraint.
#   2. Reverse of this list is the correct TRUNCATE order on restore.
#   3. Materialized views (memory_units_bm25) are NOT included — they are
#      derived from memory_units and are refreshed at the end of restore.
#   4. alembic_version is NOT included — schema version is the target DB's
#      responsibility, not the data backup's.
#   5. When a new migration adds a table, add it here in the correct layer.
#      Adding to the wrong layer causes restore to fail with a FK violation,
#      which is loud and safe (backup itself is never corrupted by this).
#
# Layer 0 — root tables (no FK parents)
# Layer 1 — reference banks directly
# Layer 2 — reference Layer 1 tables
# Layer 3 — reference Layer 2 tables
# Layer 4 — reference Layer 3 tables
# Layer 5 — reference Layer 4 tables
# ---------------------------------------------------------------------------
BACKUP_TABLES: list[str] = [
    # --- Layer 0: roots (no FK parents) ---
    "banks",
    "file_storage",
    # --- Layer 1: reference banks ---
    "documents",
    "entities",
    "async_operations",
    "forge_records",
    "forge_taste_datasets",
    "forge_taste_sets",
    "forge_transform_chains",
    "webhooks",
    "directives",
    "mental_models",
    "dream_artifacts",
    "anomaly_events",
    "pattern_library",
    "entity_trajectories",
    "entity_intelligence",
    "codebases",
    "dream_runs",
    # --- Layer 2: reference Layer 1 ---
    "memory_units",  # → banks, documents
    "chunks",  # → documents
    "entity_cooccurrences",  # → entities
    "anomaly_corrections",  # → anomaly_events
    "codebase_snapshots",  # → codebases
    "dream_predictions",  # → dream_runs
    "dream_proposals",  # → dream_runs
    # --- Layer 3: reference Layer 2 ---
    "unit_entities",  # → memory_units, entities
    "memory_links",  # → memory_units
    "codebase_files",  # → codebases, codebase_snapshots
    "codebase_symbols",  # → codebases, codebase_snapshots
    "codebase_review_routes",  # → codebase_snapshots
    "dream_prediction_outcomes",  # → dream_predictions
    # --- Layer 4: reference Layer 3 ---
    "codebase_edges",  # → codebase_symbols
    "codebase_chunks",  # → codebase_files, codebase_snapshots
    "codebase_intel_artifacts",  # → codebases, codebase_snapshots
    "codebase_saved_intents",  # → codebases
    # --- Layer 5: reference Layer 4 ---
    "codebase_chunk_edges",  # → codebase_chunks
    "codebase_auto_triage_overrides",  # → codebases, codebase_snapshots, codebase_chunks
]

# Materialized views refreshed after restore (not in COPY cycle).
REFRESH_VIEWS: list[str] = [
    "memory_units_bm25",
]

# Bump this when BACKUP_TABLES changes in a breaking way (tables added/removed).
# Restore rejects a backup whose manifest_version != MANIFEST_VERSION with a
# clear error so the operator knows to use the matching atulya-admin version.
MANIFEST_VERSION = "3"


async def _backup(database_url: str, output_path: Path, schema: str = "public") -> dict[str, Any]:
    """Backup all tables to a zip file using binary COPY protocol."""
    from atulya_api import __version__ as atulya_version

    conn = await asyncpg.connect(database_url)
    try:
        tables: dict[str, Any] = {}
        manifest: dict[str, Any] = {
            "version": MANIFEST_VERSION,
            "atulya_version": atulya_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "schema": schema,
            "table_count": len(BACKUP_TABLES),
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
            backup_version = manifest.get("version")
            if backup_version != MANIFEST_VERSION:
                raise ValueError(
                    f"[ERROR] Backup version mismatch: backup is v{backup_version}, "
                    f"this atulya-admin requires v{MANIFEST_VERSION}.\n"
                    "Use the atulya-admin version that matches the backup, or re-create "
                    "the backup with the current atulya-admin."
                )

            # Warn about tables in BACKUP_TABLES that are absent from the archive.
            # This indicates a corrupt/truncated backup — abort rather than partially restore.
            archive_files = set(zf.namelist())
            missing = [t for t in BACKUP_TABLES if f"{t}.bin" not in archive_files]
            if missing:
                raise ValueError(
                    f"[ERROR] Backup archive is missing {len(missing)} expected table(s): "
                    f"{', '.join(missing)}.\n"
                    "The backup file may be corrupt or was created with an older atulya-admin. "
                    "Do not restore from this file."
                )

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
                    expected_rows = manifest["tables"].get(table, {}).get("rows", "?")
                    typer.echo(f"  [{i}/{len(BACKUP_TABLES)}] Restoring {table}... {expected_rows} rows")

                    data = zf.read(filename)
                    buffer = io.BytesIO(data)
                    # asyncpg requires schema_name as separate parameter
                    await conn.copy_to_table(table, schema_name=schema, source=buffer, format="binary")

                # Refresh all materialized views derived from restored data
                typer.echo("  Refreshing materialized views...")
                for view in REFRESH_VIEWS:
                    qualified_view = _fq_table(view, schema)
                    await conn.execute(f"REFRESH MATERIALIZED VIEW {qualified_view}")
                    typer.echo(f"    {view} refreshed")

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
    size_bytes = sum(t.get("size_bytes", 0) for t in manifest["tables"].values())
    typer.echo(f"Backed up {len(BACKUP_TABLES)} tables, {total_rows:,} rows, {size_bytes / 1024 / 1024:.1f} MB")
    typer.echo(f"Atulya version: {manifest.get('atulya_version', 'unknown')}")
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
    typer.echo(f"Restored {len(BACKUP_TABLES)} tables, {total_rows:,} rows")
    typer.echo(
        f"Backup was from atulya v{manifest.get('atulya_version', 'unknown')} at {manifest.get('created_at', 'unknown')}"
    )
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


forge_app = typer.Typer(name="forge", help="Data Forge training dataset commands")
app.add_typer(forge_app, name="forge")


@forge_app.command("run")
def forge_run(
    bank_id: str = typer.Option(..., "--bank", help="Memory bank ID"),
    recipe: str = typer.Option("consolidation_pairs", "--recipe", help="Forge recipe ID"),
    source_file: Path | None = typer.Option(None, "--source-file", help="JSON ingest source file"),
    domain_tag: str = typer.Option("startup_ops", "--domain-tag", help="Domain profile tag"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for job completion"),
):
    """Queue a Data Forge job and optionally wait for completion."""

    async def _run() -> None:
        from atulya_api.engine.memory_engine import MemoryEngine
        from atulya_api.forge.models import ForgeIngestSource, ForgeJobRequest
        from atulya_api.models import RequestContext

        config = AtulyaConfig.from_env()
        memory = MemoryEngine(
            db_url=config.database_url or "pg0",
            memory_llm_provider=config.llm_provider,
            memory_llm_api_key=config.llm_api_key,
            memory_llm_model=config.llm_model,
            memory_llm_base_url=config.llm_base_url,
        )
        await memory.initialize()
        ctx = RequestContext(internal=True)
        source = None
        if source_file:
            payload = json.loads(source_file.read_text(encoding="utf-8"))
            source = ForgeIngestSource.model_validate(payload)
        request = ForgeJobRequest(
            recipe_id=recipe,  # type: ignore[arg-type]
            domain_tags=[domain_tag],
            source=source,
        )
        submitted = await memory.submit_forge_job(bank_id, request, request_context=ctx)
        typer.echo(f"Forge job queued: {submitted['operation_id']}")
        if not wait:
            return
        op_id = submitted["operation_id"]
        for _ in range(120):
            status = await memory.get_operation_status(bank_id, op_id, request_context=ctx)
            if status.get("status") == "completed":
                result = await memory.get_operation_result(bank_id, op_id, request_context=ctx)
                typer.echo(json.dumps(result.get("result_payload") or {}, indent=2))
                return
            if status.get("status") == "failed":
                typer.echo(f"Forge job failed: {status.get('error_message')}", err=True)
                raise typer.Exit(1)
            await asyncio.sleep(2)
        typer.echo("Timed out waiting for forge job", err=True)
        raise typer.Exit(1)

    asyncio.run(_run())


def main():
    app()


if __name__ == "__main__":
    main()
