#!/bin/bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lifecycle.sh"

LIFECYCLE_COMPONENT="start-worker"
ROOT_DIR="$(project_root_from_dev_script)"
cd "$ROOT_DIR"

require_cmd uv
ENV_FILE="$ROOT_DIR/.env"
load_env_file "$ENV_FILE"

log_info "startup.exec" "Starting Atulya worker"
exec uv run atulya-worker "$@"
