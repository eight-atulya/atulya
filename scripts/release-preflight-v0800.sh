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
BASELINE_REVISION="0800a1b2c3d4"
EXPECTED_REVISION=""

EXPECTED_TY_REFS=(
    "atulya_api/api/http.py:4539:28"
    "atulya_api/main.py:147:18"
)

EXPECTED_TABLES=(
    "alembic_version"
    "async_operations"
    "banks"
    "chunks"
    "codebase_chunk_edges"
    "codebase_chunks"
    "codebase_edges"
    "codebase_files"
    "codebase_review_routes"
    "codebase_snapshots"
    "codebase_symbols"
    "codebases"
    "directives"
    "documents"
    "dream_artifacts"
    "dream_prediction_outcomes"
    "dream_predictions"
    "dream_proposals"
    "dream_runs"
    "entities"
    "entity_cooccurrences"
    "file_storage"
    "memory_links"
    "memory_units"
    "mental_models"
    "unit_entities"
    "webhooks"
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

assert_linear_migration_chain() {
    EXPECTED_REVISION="$(
        VERSIONS_DIR="$VERSIONS_DIR" BASELINE_FILE="$BASELINE_FILE" BASELINE_REVISION="$BASELINE_REVISION" \
        uv run python - <<'PY'
import os
import re
import sys
from pathlib import Path

versions_dir = Path(os.environ["VERSIONS_DIR"])
baseline_file = Path(os.environ["BASELINE_FILE"])
baseline_revision = os.environ["BASELINE_REVISION"]

revision_re = re.compile(r'^revision:\s*str\s*=\s*"([0-9a-f]+)"$', re.MULTILINE)
down_re = re.compile(r'^down_revision:\s*str \| Sequence\[str\] \| None\s*=\s*(.+)$', re.MULTILINE)

files = sorted(path for path in versions_dir.glob("*.py") if path.name != "__init__.py")
if not files:
    print(f"No Alembic migration files found in {versions_dir}", file=sys.stderr)
    sys.exit(1)

if baseline_file not in files:
    print(f"Baseline migration file missing: {baseline_file}", file=sys.stderr)
    sys.exit(1)

revisions: dict[str, dict[str, str | None]] = {}
children: dict[str, list[str]] = {}

for path in files:
    text = path.read_text()
    revision_match = revision_re.search(text)
    down_match = down_re.search(text)
    if not revision_match or not down_match:
        print(f"Could not parse revision metadata from {path}", file=sys.stderr)
        sys.exit(1)

    revision = revision_match.group(1)
    down_raw = down_match.group(1).strip()
    if down_raw == "None":
        down_revision = None
    else:
        down_revision = down_raw.strip('"')

    if revision in revisions:
        print(f"Duplicate Alembic revision detected: {revision}", file=sys.stderr)
        sys.exit(1)

    revisions[revision] = {"path": str(path), "down_revision": down_revision}
    if down_revision is not None:
        children.setdefault(down_revision, []).append(revision)

roots = [revision for revision, meta in revisions.items() if meta["down_revision"] is None]
if roots != [baseline_revision]:
    print(f"Expected a single baseline root revision {baseline_revision}, found {roots}", file=sys.stderr)
    sys.exit(1)

baseline_meta = revisions.get(baseline_revision)
if baseline_meta is None or Path(str(baseline_meta["path"])) != baseline_file:
    print(
        f"Baseline revision {baseline_revision} is not anchored to {baseline_file}",
        file=sys.stderr,
    )
    sys.exit(1)

branch_points = {revision: refs for revision, refs in children.items() if len(refs) > 1}
if branch_points:
    print(f"Expected a linear v0.8.x migration chain, found branches: {branch_points}", file=sys.stderr)
    sys.exit(1)

heads = [revision for revision in revisions if revision not in children]
if len(heads) != 1:
    print(f"Expected exactly one Alembic head revision, found {heads}", file=sys.stderr)
    sys.exit(1)

head = heads[0]
visited = []
current = head
while current is not None:
    visited.append(current)
    current = revisions[current]["down_revision"]

if set(visited) != set(revisions):
    print(
        f"Migration chain does not cover all revisions. visited={visited}, known={sorted(revisions)}",
        file=sys.stderr,
    )
    sys.exit(1)

print(head)
PY
    )"

    print_info "Validated linear Alembic chain through head revision ${EXPECTED_REVISION}"
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
        EXPECTED_REVISION="$EXPECTED_REVISION" EXPECTED_VERSION="$EXPECTED_VERSION" EXPECTED_TABLES="$(printf '%s,' "${EXPECTED_TABLES[@]}")" uv run python - <<'PY'
import asyncio
import os

from sqlalchemy import create_engine, inspect, text

from atulya_api.migrations import check_migration_status, run_migrations
from atulya_api.pg0 import EmbeddedPostgres

EXPECTED_REVISION = os.environ["EXPECTED_REVISION"]
EXPECTED_TABLES = [table for table in os.environ["EXPECTED_TABLES"].split(",") if table]
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
assert_linear_migration_chain

print_info "Checking Alembic migrations import cleanly"
(
    cd "$API_DIR"
    uv run python -m py_compile atulya_api/alembic/versions/*.py
)

print_info "Running targeted Ruff on the v0.8.x migration chain"
(
    cd "$API_DIR"
    uv run ruff check atulya_api/alembic/versions/*.py
)

print_info "Running ty check with the current release allowlist"
run_ty_with_allowlist

print_info "Verifying fresh-database migrations for public and tenant schemas"
verify_fresh_migrations

print_info "v${EXPECTED_VERSION} release preflight passed"
