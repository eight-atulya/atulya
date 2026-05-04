#!/usr/bin/env bash
# Start Langfuse from the Atulya repository root (parent of docker/).
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATULYA_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
COMPOSE_REL="docker/docker-compose/langfuse/docker-compose.yaml"
COMPOSE_FILE="$ATULYA_ROOT/$COMPOSE_REL"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 12
fi

if ! docker network inspect atulya-network >/dev/null 2>&1; then
  echo "Creating docker network atulya-network (required; same as dev monitoring stack)"
  docker network create atulya-network
fi

cd "$ATULYA_ROOT"

if [ "$#" -eq 0 ]; then
  docker compose -f "$COMPOSE_REL" up -d
  echo ""
  echo "Langfuse UI:  http://localhost:3001"
  echo "OTLP base:    http://localhost:3001/api/public/otel  (Atulya appends /v1/traces)"
  echo "MinIO (S3):   http://localhost:9090"
  echo ""
  echo "Logs: docker compose -f $COMPOSE_REL logs -f langfuse-web"
else
  docker compose -f "$COMPOSE_REL" "$@"
fi
