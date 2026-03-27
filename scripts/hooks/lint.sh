#!/bin/bash
# Parallel linting for all code (Node, Python)
# Runs all linting tasks concurrently for faster execution

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# Track all background jobs
declare -a PIDS
declare -a NAMES

run_task() {
    local name="$1"
    local dir="$2"
    shift 2
    local cmd="$@"

    (
        cd "$dir"
        if OUTPUT=$($cmd 2>&1); then
            echo "OK" > "$TEMP_DIR/$name.status"
        else
            echo "FAIL" > "$TEMP_DIR/$name.status"
            echo "$OUTPUT" > "$TEMP_DIR/$name.output"
        fi
    ) &
    PIDS+=($!)
    NAMES+=("$name")
}

echo "  Syncing Python dependencies..."
# Run uv sync first to avoid race conditions when multiple uv run commands
# try to reinstall local packages in parallel (e.g., after version bump)
uv sync --quiet

echo "  Running lints in parallel..."

# Node/TypeScript tasks
run_task "eslint" "$REPO_ROOT/atulya-control-plane" "npx eslint --fix src/**/*.{ts,tsx}"
run_task "prettier" "$REPO_ROOT/atulya-control-plane" "npx prettier --write src/**/*.{ts,tsx}"

# Python atulya-api tasks
run_task "ruff-api-check" "$REPO_ROOT/atulya-api" "uv run ruff check --fix ."
run_task "ruff-api-format" "$REPO_ROOT/atulya-api" "uv run ruff format ."
run_task "ty-api" "$REPO_ROOT/atulya-api" "uv run ty check atulya_api"

# Python atulya-dev tasks
run_task "ruff-dev-check" "$REPO_ROOT/atulya-dev" "uv run ruff check --fix ."
run_task "ruff-dev-format" "$REPO_ROOT/atulya-dev" "uv run ruff format ."
run_task "ty-dev" "$REPO_ROOT/atulya-dev" "uv run ty check atulya_dev benchmarks"

# Python atulya-embed tasks
run_task "ruff-embed-check" "$REPO_ROOT/atulya-embed" "uv run ruff check --fix ."
run_task "ruff-embed-format" "$REPO_ROOT/atulya-embed" "uv run ruff format ."
run_task "ty-embed" "$REPO_ROOT/atulya-embed" "uv run ty check atulya_embed"

# Wait for all tasks to complete
for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
done

# Check results
FAILED=0
for name in "${NAMES[@]}"; do
    if [ -f "$TEMP_DIR/$name.status" ]; then
        STATUS=$(cat "$TEMP_DIR/$name.status")
        if [ "$STATUS" = "FAIL" ]; then
            echo ""
            echo "  ❌ $name failed:"
            cat "$TEMP_DIR/$name.output"
            FAILED=1
        fi
    else
        echo "  ❌ $name: no status (crashed?)"
        FAILED=1
    fi
done

if [ $FAILED -eq 1 ]; then
    exit 1
fi

echo "  All lints passed ✓"
