#!/bin/bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lifecycle.sh"

LIFECYCLE_COMPONENT="start-control-plane"
ROOT_DIR="$(project_root_from_dev_script)"
cd "$ROOT_DIR"

require_cmd npm

# Preserve caller overrides before .env is loaded.
CALLER_PORT="${PORT:-}"
CALLER_DATAPLANE_URL="${ATULYA_CP_DATAPLANE_API_URL:-}"
CALLER_HOSTNAME="${HOSTNAME:-}"

ENV_FILE="$ROOT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
  load_env_file "$ENV_FILE"
else
  log_warn "env.missing" ".env not found at $ENV_FILE; using defaults/caller overrides"
fi

export HOSTNAME="${CALLER_HOSTNAME:-${ATULYA_CP_HOSTNAME:-0.0.0.0}}"
export PORT="${CALLER_PORT:-${ATULYA_CP_PORT:-9999}}"
export ATULYA_CP_DATAPLANE_API_URL="${CALLER_DATAPLANE_URL:-${ATULYA_CP_DATAPLANE_API_URL:-http://localhost:8888}}"

log_info "startup.config" "Resolved control-plane host=$HOSTNAME port=$PORT dataplane=$ATULYA_CP_DATAPLANE_API_URL"

if [ -z "$CALLER_PORT" ]; then
  ensure_port_available "$PORT"
fi

log_info "build.sdk" "Building TypeScript SDK workspace dependency"
npm run build -w @eight-atulya/atulya-client

log_info "startup.exec" "Starting Control Plane Next.js development server"
exec npm run dev -w @eight-atulya/atulya-control-plane