#!/bin/bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIFECYCLE_COMPONENT="start-monitoring"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/../lifecycle.sh"

API_PORT="${API_PORT:-8888}"
cd "$SCRIPT_DIR"

if command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
elif command -v docker >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
else
  fail_with 12 "preflight.command_missing" "docker-compose or docker compose is required"
fi

log_info "startup.banner" "Starting Atulya Monitoring Stack (Grafana LGTM)"

if ! curl -sf "http://localhost:$API_PORT/metrics" >/dev/null 2>&1; then
  log_warn "preflight.api_not_detected" "Atulya API not detected at localhost:$API_PORT; start API first with ./scripts/dev/start-api.sh"
fi

log_info "startup.endpoint" "Grafana: http://localhost:3000"
log_info "startup.endpoint" "OTLP HTTP: http://localhost:4318"
log_info "startup.endpoint" "OTLP gRPC: http://localhost:4317"
log_info "startup.endpoint" "API metrics: http://localhost:$API_PORT/metrics"

"${COMPOSE_CMD[@]}" up
