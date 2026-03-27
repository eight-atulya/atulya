#!/usr/bin/env bash
set -euo pipefail

# Verify integrity of assembled runtime artifacts.
# Usage: ./scripts/verify-runtime.sh [runtime_dir]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="${1:-$PROJECT_ROOT/.dist/runtime}"

echo "==> Verifying runtime integrity: $RUNTIME_DIR"

ERRORS=0

# Check required directories
for dir in api control-plane brain; do
    if [ ! -d "$RUNTIME_DIR/$dir" ]; then
        echo "    FAIL: missing directory $dir/"
        ERRORS=$((ERRORS + 1))
    else
        echo "    OK:   $dir/"
    fi
done

# Check API has venv
if [ ! -d "$RUNTIME_DIR/api/.venv" ]; then
    echo "    FAIL: API .venv missing"
    ERRORS=$((ERRORS + 1))
else
    echo "    OK:   api/.venv"
fi

# Check control plane has server.js
if [ ! -f "$RUNTIME_DIR/control-plane/server.js" ]; then
    echo "    FAIL: control-plane/server.js missing"
    ERRORS=$((ERRORS + 1))
else
    echo "    OK:   control-plane/server.js"
fi

# Check brain native library
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$OS" in
    darwin) BRAIN_LIB="brain/libatulya_brain.dylib" ;;
    linux)  BRAIN_LIB="brain/libatulya_brain.so" ;;
    *)      BRAIN_LIB="" ;;
esac

if [ -n "$BRAIN_LIB" ]; then
    if [ ! -f "$RUNTIME_DIR/$BRAIN_LIB" ]; then
        echo "    FAIL: $BRAIN_LIB missing"
        ERRORS=$((ERRORS + 1))
    else
        echo "    OK:   $BRAIN_LIB"
    fi
fi

# Verify checksums if present
CHECKSUM_FILE="$RUNTIME_DIR/checksums.sha256"
if [ -f "$CHECKSUM_FILE" ]; then
    echo "==> Verifying checksums..."
    CHECKSUM_ERRORS=0
    while IFS= read -r line; do
        EXPECTED_HASH=$(echo "$line" | awk '{print $1}')
        REL_PATH=$(echo "$line" | awk '{print $2}')
        FULL_PATH="$RUNTIME_DIR/$REL_PATH"
        if [ -f "$FULL_PATH" ]; then
            ACTUAL_HASH=$(shasum -a 256 "$FULL_PATH" | awk '{print $1}')
            if [ "$EXPECTED_HASH" != "$ACTUAL_HASH" ]; then
                echo "    FAIL: checksum mismatch for $REL_PATH"
                CHECKSUM_ERRORS=$((CHECKSUM_ERRORS + 1))
            fi
        else
            echo "    FAIL: file missing: $REL_PATH"
            CHECKSUM_ERRORS=$((CHECKSUM_ERRORS + 1))
        fi
    done < "$CHECKSUM_FILE"

    if [ "$CHECKSUM_ERRORS" -eq 0 ]; then
        echo "    OK:   all checksums verified"
    else
        ERRORS=$((ERRORS + CHECKSUM_ERRORS))
    fi
else
    echo "    WARN: no checksums.sha256 found, skipping verification"
fi

echo ""
if [ "$ERRORS" -gt 0 ]; then
    echo "==> FAILED: $ERRORS error(s) found"
    exit 1
else
    echo "==> PASSED: runtime integrity verified"
fi
