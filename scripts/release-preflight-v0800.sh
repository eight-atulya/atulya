#!/bin/bash
set -Eeuo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
API_DIR="$ROOT_DIR/atulya-api"
VERSIONS_DIR="$API_DIR/atulya_api/alembic/versions"
BASELINE_FILE="$VERSIONS_DIR/0800a1b2c3d4_v0800_schema_baseline.py"
EXPECTED_VERSION="${1:-0.8.0}"
EXPECTED_REVISION="0800a1b2c3d4"

EXPECTED_TY_REFS=(
    "atulya_api/api/http.py:4539:28"
    "atulya_api/main.py:147:18"
)

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        print_error "Required command not found: $1"
        exit 1
    fi
}

assert_file_exists() {
    if [ ! -f "$1" ]; then
        print_error "Required file not found: $1"
        exit 1
    fi
}

assert_single_baseline_file() {
    migration_files=()
    while IFS= read -r line; do
        migration_files+=("$line")
    done < <(find "$VERSIONS_DIR" -maxdepth 1 -type f -name '*.py' | sort)

    if [ "${#migration_files[@]}" -ne 1 ]; then
        print_error "Expected exactly 1 Alembic migration file in $VERSIONS_DIR, found ${#migration_files[@]}"
        printf ' - %s\n' "${migration_files[@]}"
        exit 1
    fi
    if [ "${migration_files[0]}" != "$BASELINE_FILE" ]; then
        print_error "Unexpected baseline migration file: ${migration_files[0]}"
        exit 1
    fi
}

run_ty_with_allowlist() {
    local log_file
    log_file="$(mktemp)"
    trap 'rm -f "$log_file"' RETURN

    set +e
    (
        cd "$API_DIR"
        uv run ty check atulya_api
    ) >"$log_file" 2>&1
    local status=$?
    set -e

    if [ $status -eq 0 ]; then
        print_info "ty check passed"
        return 0
    fi

    actual_refs=()
    while IFS= read -r line; do
        actual_refs+=("$line")
    done < <(rg -o 'atulya_api/[^:]+:[0-9]+:[0-9]+' "$log_file" | sort -u || true)

    if diff -u <(printf '%s\n' "${EXPECTED_TY_REFS[@]}") <(printf '%s\n' "${actual_refs[@]}") >/dev/null; then
        print_warn "ty check still reports the known pre-existing blockers only:"
        printf ' - %s\n' "${EXPECTED_TY_REFS[@]}"
        return 0
    fi

    print_error "ty check produced unexpected diagnostics:"
    cat "$log_file"
    exit 1
}

verify_fresh_migrations() {
    (
        cd "$API_DIR"
        EXPECTED_REVISION="$EXPECTED_REVISION" EXPECTED_VERSION="$EXPECTED_VERSION" uv run python - <<'PY'
import asyncio
import os

from sqlalchemy import create_engine, inspect, text

from atulya_api.migrations import check_migration_status, run_migrations
from atulya_api.pg0 import EmbeddedPostgres

EXPECTED_REVISION = os.environ["EXPECTED_REVISION"]
EXPECTED_TABLES = [
    "alembic_version",
    "async_operations",
    "banks",
    "chunks",
    "directives",
    "documents",
    "dream_artifacts",
    "entities",
    "entity_cooccurrences",
    "file_storage",
    "memory_links",
    "memory_units",
    "mental_models",
    "unit_entities",
    "webhooks",
]
EXPECTED_MATVIEWS = ["memory_units_bm25"]


async def verify(schema: str | None) -> None:
    suffix = schema or "public"
    pg = EmbeddedPostgres(name=f"atulya-v0800-preflight-{suffix}")
    url = await pg.ensure_running()
    try:
        run_migrations(url, schema=schema)
        run_migrations(url, schema=schema)

        engine = create_engine(url.replace("+asyncpg", ""))
        target_schema = schema or "public"

        with engine.connect() as conn:
            insp = inspect(conn)
            tables = sorted(insp.get_table_names(schema=target_schema))
            matviews = [
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT matviewname FROM pg_matviews "
                        "WHERE schemaname = :schema ORDER BY matviewname"
                    ),
                    {"schema": target_schema},
                ).fetchall()
            ]

            assert tables == EXPECTED_TABLES, (target_schema, tables)
            assert matviews == EXPECTED_MATVIEWS, (target_schema, matviews)

            if schema is None:
                current, head = check_migration_status(url)
                assert current == EXPECTED_REVISION, current
                assert head == EXPECTED_REVISION, head
            else:
                version = conn.execute(
                    text(f'SELECT version_num FROM "{target_schema}".alembic_version')
                ).scalar()
                assert version == EXPECTED_REVISION, version
    finally:
        await pg.stop()


async def main() -> None:
    await verify(None)
    await verify("tenant_v0800_preflight")


asyncio.run(main())
PY
    )
}

print_info "Running v${EXPECTED_VERSION} release preflight"

require_cmd uv
require_cmd rg
assert_file_exists "$BASELINE_FILE"
assert_single_baseline_file

print_info "Checking baseline migration imports cleanly"
(
    cd "$API_DIR"
    uv run python -m py_compile "atulya_api/alembic/versions/0800a1b2c3d4_v0800_schema_baseline.py"
)

print_info "Running targeted Ruff on the v0.8.0 baseline migration"
(
    cd "$API_DIR"
    uv run ruff check "atulya_api/alembic/versions/0800a1b2c3d4_v0800_schema_baseline.py"
)

print_info "Running ty check with the current release allowlist"
run_ty_with_allowlist

print_info "Verifying fresh-database migrations for public and tenant schemas"
verify_fresh_migrations

print_info "v${EXPECTED_VERSION} release preflight passed"
