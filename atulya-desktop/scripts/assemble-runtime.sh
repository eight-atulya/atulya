#!/usr/bin/env bash
set -euo pipefail

# Assemble Atulya Desktop runtime artifacts into .dist/runtime/
# Usage: ./scripts/assemble-runtime.sh [--target <os-arch>]
#
# This script is the single entry point for building the portable runtime
# bundle that the Tauri shell manages. It must be run on the matching OS
# (macOS runner for darwin artifacts, etc).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MONOREPO_ROOT="$(cd "$PROJECT_ROOT/.." && pwd)"
DIST_DIR="$PROJECT_ROOT/.dist/runtime"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64) ARCH="x64" ;;
    aarch64|arm64) ARCH="arm64" ;;
esac
TARGET="${1:-$OS-$ARCH}"

echo "==> Assembling runtime for target: $TARGET"
echo "    monorepo: $MONOREPO_ROOT"
echo "    output:   $DIST_DIR"

rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR/api"
mkdir -p "$DIST_DIR/control-plane"
mkdir -p "$DIST_DIR/brain"

# ── Step 1: Build API runtime ─────────────────────────────────────────
echo "==> [1/4] Building API runtime..."
API_SRC="$MONOREPO_ROOT/atulya-api"

if [ -d "$API_SRC" ]; then
    cp -r "$API_SRC/atulya_api" "$DIST_DIR/api/atulya_api"
    cp "$API_SRC/pyproject.toml" "$DIST_DIR/api/"
    cp "$API_SRC/README.md" "$DIST_DIR/api/" 2>/dev/null || true

    pushd "$DIST_DIR/api" > /dev/null
    if command -v uv &>/dev/null; then
        uv venv .venv
        uv sync
        uv pip install -e .
    else
        python3 -m venv .venv
        .venv/bin/pip install -e .
    fi
    popd > /dev/null
    echo "    API runtime assembled"
else
    echo "    WARNING: $API_SRC not found, skipping API"
fi

# ── Step 2: Build Control Plane ────────────────────────────────────────
echo "==> [2/4] Building Control Plane..."
CP_SRC="$MONOREPO_ROOT/atulya-control-plane"

if [ -d "$CP_SRC" ]; then
    pushd "$CP_SRC" > /dev/null
    npm ci --ignore-scripts 2>/dev/null || npm install
    npx next build
    popd > /dev/null

    # Extract standalone output
    STANDALONE_ROOT=$(find "$CP_SRC/.next/standalone" -path '*/node_modules' -prune -o -name 'server.js' -print | head -1 | xargs dirname)
    if [ -n "$STANDALONE_ROOT" ] && [ -f "$STANDALONE_ROOT/server.js" ]; then
        cp -r "$STANDALONE_ROOT"/* "$DIST_DIR/control-plane/"
        cp -r "$STANDALONE_ROOT/.next" "$DIST_DIR/control-plane/.next" 2>/dev/null || true
        if [ -d "$CP_SRC/.next/static" ]; then
            mkdir -p "$DIST_DIR/control-plane/.next/static"
            cp -r "$CP_SRC/.next/static"/* "$DIST_DIR/control-plane/.next/static/"
        fi
        if [ -d "$CP_SRC/public" ]; then
            mkdir -p "$DIST_DIR/control-plane/public"
            cp -r "$CP_SRC/public"/* "$DIST_DIR/control-plane/public/" 2>/dev/null || true
        fi
        echo "    Control Plane assembled"
    else
        echo "    WARNING: standalone server.js not found after build"
    fi
else
    echo "    WARNING: $CP_SRC not found, skipping Control Plane"
fi

# ── Step 3: Build brain native library ─────────────────────────────────
echo "==> [3/4] Building brain native library..."
BRAIN_SRC="$MONOREPO_ROOT/atulya-brain"

if [ -d "$BRAIN_SRC" ]; then
    pushd "$BRAIN_SRC" > /dev/null
    cargo build --release
    popd > /dev/null

    case "$OS" in
        darwin)
            cp "$BRAIN_SRC/target/release/libatulya_brain.dylib" "$DIST_DIR/brain/" 2>/dev/null || true
            ;;
        linux)
            cp "$BRAIN_SRC/target/release/libatulya_brain.so" "$DIST_DIR/brain/" 2>/dev/null || true
            ;;
    esac
    echo "    Brain native library assembled"
else
    echo "    WARNING: $BRAIN_SRC not found, skipping brain"
fi

# ── Step 4: Generate checksums ─────────────────────────────────────────
echo "==> [4/4] Generating checksums..."
CHECKSUM_FILE="$DIST_DIR/checksums.sha256"
: > "$CHECKSUM_FILE"

find "$DIST_DIR" -type f ! -name "checksums.sha256" -print0 | sort -z | while IFS= read -r -d '' file; do
    REL_PATH="${file#"$DIST_DIR"/}"
    SHA=$(shasum -a 256 "$file" | awk '{print $1}')
    echo "$SHA  $REL_PATH" >> "$CHECKSUM_FILE"
done

MANIFEST_HASH=$(shasum -a 256 "$CHECKSUM_FILE" | awk '{print $1}')
echo ""
echo "==> Runtime assembly complete"
echo "    Target:   $TARGET"
echo "    Output:   $DIST_DIR"
echo "    Manifest: $MANIFEST_HASH"
