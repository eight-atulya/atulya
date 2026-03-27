#!/bin/bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lifecycle.sh"

LIFECYCLE_COMPONENT="dev-start"
ROOT_DIR="$(project_root_from_dev_script)"
cd "$ROOT_DIR"

require_cmd python3
require_cmd curl

RANDOM_PORT=false
START_API=true
START_CP=true
START_WORKER=false
SKIP_WAIT=false
LOG_DIR=""
WITH_BRAIN_NATIVE=false

while (($#)); do
  case "$1" in
    --random-port)
      RANDOM_PORT=true
      shift
      ;;
    --api-only)
      START_API=true
      START_CP=false
      shift
      ;;
    --cp-only)
      START_API=false
      START_CP=true
      shift
      ;;
    --with-worker)
      START_WORKER=true
      shift
      ;;
    --no-wait)
      SKIP_WAIT=true
      shift
      ;;
    --log-dir)
      LOG_DIR="${2:-}"
      if [ -z "$LOG_DIR" ]; then
        fail_with 10 "preflight.invalid_args" "Missing value for --log-dir"
      fi
      shift 2
      ;;
    --with-brain-native)
      WITH_BRAIN_NATIVE=true
      shift
      ;;
    *)
      fail_with 10 "preflight.invalid_args" "Unknown flag: $1"
      ;;
  esac
done

if [ "$START_API" = false ] && [ "$START_CP" = false ] && [ "$START_WORKER" = false ]; then
  fail_with 10 "preflight.invalid_args" "No services selected"
fi

ENV_FILE="$ROOT_DIR/.env"
load_env_file "$ENV_FILE"

get_free_port() {
  python3 -c "import socket; s=socket.socket(); s.bind(('', 0)); print(s.getsockname()[1]); s.close()"
}

if [ "$RANDOM_PORT" = true ]; then
  API_PORT="$(get_free_port)"
  CP_PORT="$(get_free_port)"
else
  API_PORT="${ATULYA_API_PORT:-8888}"
  CP_PORT="${ATULYA_CP_PORT:-9999}"
fi

if [ -n "$LOG_DIR" ]; then
  mkdir -p "$LOG_DIR"
  log_info "startup.logs" "Log directory enabled at $LOG_DIR"
fi

if [ "$START_API" = true ]; then
  if [ "$RANDOM_PORT" = false ]; then
    ensure_port_available "$API_PORT"
  fi
fi
if [ "$START_CP" = true ]; then
  if [ "$RANDOM_PORT" = false ]; then
    ensure_port_available "$CP_PORT"
  fi
fi

log_info "startup.config" "services api=$START_API cp=$START_CP worker=$START_WORKER random_port=$RANDOM_PORT api_port=$API_PORT cp_port=$CP_PORT wait=$([ "$SKIP_WAIT" = true ] && echo no || echo yes) brain_native=$WITH_BRAIN_NATIVE"

cleanup() {
  graceful_shutdown_children
}
trap cleanup EXIT INT TERM

start_child() {
  local name="$1"
  shift
  if [ -n "$LOG_DIR" ]; then
    local logfile="$LOG_DIR/$name.log"
    "$@" >"$logfile" 2>&1 &
  else
    "$@" &
  fi
  local pid=$!
  register_child "$name" "$pid"
}

if [ "$START_API" = true ]; then
  log_info "startup.api" "Starting API"
  if [ "$WITH_BRAIN_NATIVE" = true ]; then
    start_child "api" env ATULYA_API_BRAIN_NATIVE_AUTO_BUILD=true "$SCRIPT_DIR/start-api.sh" --port "$API_PORT"
  else
    start_child "api" "$SCRIPT_DIR/start-api.sh" --port "$API_PORT"
  fi

  if [ "$SKIP_WAIT" = false ]; then
    wait_for_http "api" "http://localhost:${API_PORT}/health" 120 || fail_with 21 "readiness.timeout" "API readiness failed"
  fi
fi

if [ "$START_WORKER" = true ]; then
  log_info "startup.worker" "Starting worker"
  start_child "worker" "$SCRIPT_DIR/start-worker.sh"
fi

if [ "$START_CP" = true ]; then
  log_info "startup.control_plane" "Starting control plane"
  if [ "$START_API" = true ]; then
    start_child "control-plane" env PORT="$CP_PORT" ATULYA_CP_DATAPLANE_API_URL="http://localhost:${API_PORT}" "$SCRIPT_DIR/start-control-plane.sh"
  else
    start_child "control-plane" env PORT="$CP_PORT" "$SCRIPT_DIR/start-control-plane.sh"
  fi
fi

log_info "startup.ready" "Atulya services running"
[ "$START_API" = true ] && log_info "startup.endpoint" "API: http://localhost:${API_PORT}"
[ "$START_CP" = true ] && log_info "startup.endpoint" "Control Plane: http://localhost:${CP_PORT}"
[ "$START_WORKER" = true ] && log_info "startup.endpoint" "Worker: background task poller active"

while true; do
  check_children_alive || fail_with 31 "process.child_crash" "One or more child processes exited unexpectedly"
  sleep 2
done
