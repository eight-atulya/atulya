#!/bin/bash
set -e

# Script to generate OpenAPI specification and update documentation
# This runs the generate-openapi command from atulya-dev and regenerates docs

cd "$(dirname "$0")/.."
ROOT_DIR=$(pwd)

echo "Generating OpenAPI specification..."
cd atulya-dev
uv run generate-openapi

echo ""
echo "Building documentation..."
cd "$ROOT_DIR/atulya-docs"
npm run build

echo ""
echo "OpenAPI spec and documentation generated successfully!"
