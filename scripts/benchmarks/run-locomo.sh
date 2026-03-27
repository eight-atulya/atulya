#!/bin/bash
set -e

cd "$(dirname "$0")/../.."

# Parse --env argument to source the right env file

ARGS=("$@")
ENV_FILE=".env"
if [ ! -f "$ENV_FILE" ]; then
  echo "Error: Environment file $ENV_FILE not found"
  exit 1
fi

echo "🚀 Starting LoComo Benchmark"
echo "📄 Loading environment from $ENV_FILE"
echo ""

# Export all variables from env file
set -a
source "$ENV_FILE"
set +a

uv run python atulya-dev/benchmarks/locomo/locomo_benchmark.py "${ARGS[@]}"
