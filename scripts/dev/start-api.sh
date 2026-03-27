#!/bin/bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lifecycle.sh"

LIFECYCLE_COMPONENT="start-api"
ROOT_DIR="$(project_root_from_dev_script)"
cd "$ROOT_DIR"

require_cmd uv
require_cmd curl

ENV_FILE="$ROOT_DIR/.env"
load_env_file "$ENV_FILE"

BRAIN_AUTO_BUILD="${ATULYA_API_BRAIN_NATIVE_AUTO_BUILD:-false}"
resolve_brain_native_lib() {
  local candidates=(
    "$ROOT_DIR/atulya-brain/target/release/libatulya_brain.dylib"
    "$ROOT_DIR/atulya-brain/target/release/libatulya_brain.so"
    "$ROOT_DIR/atulya-brain/target/release/atulya_brain.dll"
    "$ROOT_DIR/artifacts/brain-native-darwin-arm64/libatulya_brain-darwin-arm64.dylib"
    "$ROOT_DIR/artifacts/brain-native-darwin-amd64/libatulya_brain-darwin-amd64.dylib"
    "$ROOT_DIR/artifacts/brain-native-linux-amd64/libatulya_brain-linux-amd64.so"
    "$ROOT_DIR/artifacts/brain-native-linux-arm64/libatulya_brain-linux-arm64.so"
  )
  for candidate in "${candidates[@]}"; do
    if [ -f "$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

if [ "${ATULYA_API_BRAIN_ENABLED:-false}" = "true" ]; then
  if [ -n "${ATULYA_API_BRAIN_NATIVE_LIBRARY_PATH:-}" ]; then
    log_info "brain.native" "Using native library path: ${ATULYA_API_BRAIN_NATIVE_LIBRARY_PATH}"
  elif resolved_lib="$(resolve_brain_native_lib)"; then
    export ATULYA_API_BRAIN_NATIVE_LIBRARY_PATH="$resolved_lib"
    log_info "brain.native" "Auto-resolved native library path: ${ATULYA_API_BRAIN_NATIVE_LIBRARY_PATH}"
  elif [ "$BRAIN_AUTO_BUILD" = "true" ]; then
    if command -v cargo >/dev/null 2>&1; then
      log_info "brain.auto_build" "ATULYA_API_BRAIN_NATIVE_AUTO_BUILD=true, building native library"
      "$SCRIPT_DIR/build-brain.sh" >/tmp/atulya-brain-build.log 2>&1 || {
        log_warn "brain.auto_build_failed" "Native build failed; continuing with Python fallback (see /tmp/atulya-brain-build.log)"
      }
      if resolved_lib="$(resolve_brain_native_lib)"; then
        export ATULYA_API_BRAIN_NATIVE_LIBRARY_PATH="$resolved_lib"
      fi
      if [ -n "${ATULYA_API_BRAIN_NATIVE_LIBRARY_PATH:-}" ]; then
        log_info "brain.native" "Resolved native library: ${ATULYA_API_BRAIN_NATIVE_LIBRARY_PATH}"
      else
        log_warn "brain.native_missing" "Native library artifact not found; continuing with Python fallback"
      fi
    else
      log_warn "brain.cargo_missing" "Brain enabled but cargo is not installed; continuing with Python fallback"
    fi
  else
    log_info "brain.fallback" "Brain enabled without native path; running with Python fallback runtime"
  fi
fi

PORT_OVERRIDE=""
API_ARGS=()
while (($#)); do
  case "$1" in
    --port)
      PORT_OVERRIDE="${2:-}"
      if [ -z "$PORT_OVERRIDE" ]; then
        fail_with 10 "preflight.invalid_args" "Missing value for --port"
      fi
      API_ARGS+=("$1" "$PORT_OVERRIDE")
      shift 2
      ;;
    *)
      API_ARGS+=("$1")
      shift
      ;;
  esac
done

EFFECTIVE_PORT="${PORT_OVERRIDE:-${ATULYA_API_PORT:-8888}}"
log_info "startup.config" "Resolved API port=$EFFECTIVE_PORT"

if [ -z "$PORT_OVERRIDE" ]; then
  # Only enforce port preflight when this script controls the chosen port.
  ensure_port_available "$EFFECTIVE_PORT"
fi

log_info "startup.exec" "Starting Atulya API"
exec uv run atulya-api "${API_ARGS[@]}"
