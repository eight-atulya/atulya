#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$PACKAGE_DIR/../.." && pwd)"
OPENAPI_SPEC="$PROJECT_ROOT/atulya-docs/static/openapi.json"
OUTPUT_DIR="$PACKAGE_DIR/generated"
OPENAPI_TS_VERSION="${OPENAPI_TS_VERSION:-0.88.0}"
TEMP_PREFIX="$(mktemp -d)"

cleanup() {
    rm -rf "$TEMP_PREFIX"
}

trap cleanup EXIT

if [ ! -f "$OPENAPI_SPEC" ]; then
    echo "❌ Error: OpenAPI spec not found at $OPENAPI_SPEC"
    exit 1
fi

# Run the generator from an isolated temp prefix so clean releases do not depend
# on workspace-installed node_modules resolution for @hey-api/openapi-ts.
npm exec --yes --prefix "$TEMP_PREFIX" --package "@hey-api/openapi-ts@${OPENAPI_TS_VERSION}" -- \
    openapi-ts \
    -c @hey-api/client-fetch \
    -i "$OPENAPI_SPEC" \
    -o "$OUTPUT_DIR" \
    -p @hey-api/typescript @hey-api/sdk \
    --no-log-file
