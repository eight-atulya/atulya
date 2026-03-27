#!/bin/bash

# Shared lifecycle helpers for Atulya startup scripts.
# Designed for bash 3.2+ compatibility (macOS default bash).

set -o pipefail

LIFECYCLE_COMPONENT="${LIFECYCLE_COMPONENT:-lifecycle}"
LIFECYCLE_SHUTDOWN_TIMEOUT="${LIFECYCLE_SHUTDOWN_TIMEOUT:-20}"
LIFECYCLE_SHUTDOWN_ESCALATION_TIMEOUT="${LIFECYCLE_SHUTDOWN_ESCALATION_TIMEOUT:-5}"

CHILD_PIDS=()
CHILD_NAMES=()
SHUTDOWN_IN_PROGRESS=0
SHUTDOWN_BANNER_PRINTED=0

now_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

_log() {
  local level="$1"
  local event="$2"
  local message="$3"
  printf '%s [%s] [%s] [%s] %s\n' "$(now_utc)" "$level" "$LIFECYCLE_COMPONENT" "$event" "$message"
}

log_info() {
  _log "INFO" "$1" "$2"
}

log_warn() {
  _log "WARN" "$1" "$2"
}

log_error() {
  _log "ERROR" "$1" "$2"
}

fail_with() {
  local exit_code="$1"
  local event="$2"
  local message="$3"
  log_error "$event" "$message"
  exit "$exit_code"
}

script_dir() {
  local source_path="${BASH_SOURCE[0]}"
  while [ -L "$source_path" ]; do
    local source_dir
    source_dir="$(cd -P "$(dirname "$source_path")" && pwd)"
    source_path="$(readlink "$source_path")"
    [[ "$source_path" != /* ]] && source_path="$source_dir/$source_path"
  done
  cd -P "$(dirname "$source_path")" && pwd
}

project_root_from_dev_script() {
  local this_dir
  this_dir="$(script_dir)"
  cd "$this_dir/../.." && pwd
}

load_env_file() {
  local env_file="$1"
  if [ ! -f "$env_file" ]; then
    return 0
  fi
  log_info "env.load" "Loading environment from $env_file"
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
}

require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || fail_with 12 "preflight.command_missing" "Required command not found: $cmd"
}

is_port_in_use() {
  local port="$1"
  lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

ensure_port_available() {
  local port="$1"
  if is_port_in_use "$port"; then
    fail_with 11 "preflight.port_in_use" "Port $port is already in use"
  fi
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local timeout_seconds="$3"
  local wait_interval="${4:-1}"
  local elapsed=0

  log_info "readiness.wait_start" "Waiting for $name at $url (timeout=${timeout_seconds}s)"
  while [ "$elapsed" -lt "$timeout_seconds" ]; do
    if curl -sf "$url" >/dev/null 2>&1; then
      log_info "readiness.ready" "$name is ready after ${elapsed}s"
      return 0
    fi
    sleep "$wait_interval"
    elapsed=$((elapsed + wait_interval))
  done

  log_error "readiness.timeout" "$name did not become ready within ${timeout_seconds}s"
  return 1
}

register_child() {
  local name="$1"
  local pid="$2"
  CHILD_NAMES+=("$name")
  CHILD_PIDS+=("$pid")
  log_info "process.register" "Registered child '$name' with pid=$pid"
}

is_pid_running() {
  local pid="$1"
  kill -0 "$pid" >/dev/null 2>&1
}

check_children_alive() {
  local i
  for ((i = 0; i < ${#CHILD_PIDS[@]}; i++)); do
    local pid="${CHILD_PIDS[$i]}"
    local name="${CHILD_NAMES[$i]}"
    if ! is_pid_running "$pid"; then
      log_error "process.exited" "Child '$name' exited unexpectedly (pid=$pid)"
      return 1
    fi
  done
  return 0
}

terminate_pid_tree_signal() {
  local signal="$1"
  local pid="$2"
  local children
  children=$(pgrep -P "$pid" 2>/dev/null) || true
  local child
  for child in $children; do
    terminate_pid_tree_signal "$signal" "$child"
  done
  kill "-$signal" "$pid" 2>/dev/null || true
}

graceful_shutdown_children() {
  if [ "$SHUTDOWN_IN_PROGRESS" -eq 1 ]; then
    return 0
  fi
  SHUTDOWN_IN_PROGRESS=1

  if [ "${#CHILD_PIDS[@]}" -eq 0 ]; then
    return 0
  fi

  log_info "shutdown.start" "Stopping ${#CHILD_PIDS[@]} child process(es)"
  local i
  for ((i = 0; i < ${#CHILD_PIDS[@]}; i++)); do
    local pid="${CHILD_PIDS[$i]}"
    local name="${CHILD_NAMES[$i]}"
    if is_pid_running "$pid"; then
      log_info "shutdown.signal" "Sending SIGTERM to '$name' (pid=$pid)"
      terminate_pid_tree_signal "TERM" "$pid"
    fi
  done

  local elapsed=0
  while [ "$elapsed" -lt "$LIFECYCLE_SHUTDOWN_TIMEOUT" ]; do
    local all_stopped=true
    for pid in "${CHILD_PIDS[@]}"; do
      if is_pid_running "$pid"; then
        all_stopped=false
        break
      fi
    done
    if [ "$all_stopped" = true ]; then
      log_info "shutdown.complete" "All child processes stopped gracefully"
      print_shutdown_banner
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  log_warn "shutdown.escalate" "Graceful timeout reached; sending SIGINT to remaining children"
  for pid in "${CHILD_PIDS[@]}"; do
    if is_pid_running "$pid"; then
      terminate_pid_tree_signal "INT" "$pid"
    fi
  done

  local escalation_elapsed=0
  while [ "$escalation_elapsed" -lt "$LIFECYCLE_SHUTDOWN_ESCALATION_TIMEOUT" ]; do
    local all_stopped=true
    for pid in "${CHILD_PIDS[@]}"; do
      if is_pid_running "$pid"; then
        all_stopped=false
        break
      fi
    done
    if [ "$all_stopped" = true ]; then
      log_info "shutdown.complete" "All child processes stopped after escalation"
      print_shutdown_banner
      return 0
    fi
    sleep 1
    escalation_elapsed=$((escalation_elapsed + 1))
  done

  log_warn "shutdown.force_kill" "Escalation timeout reached; forcing remaining children"
  for pid in "${CHILD_PIDS[@]}"; do
    if is_pid_running "$pid"; then
      terminate_pid_tree_signal "KILL" "$pid"
    fi
  done
  log_info "shutdown.complete" "Forced shutdown completed"
  print_shutdown_banner
}

print_shutdown_banner() {
  if [ "$SHUTDOWN_BANNER_PRINTED" -eq 1 ]; then
    return 0
  fi
  SHUTDOWN_BANNER_PRINTED=1
  local red=""
  local reset=""
  # Respect NO_COLOR and only emit ANSI when stdout is a terminal.
  if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    red=$'\033[38;2;239;68;68m'
    reset=$'\033[0m'
  fi
  printf '\n'
  printf '%b  █████╗ ████████╗██╗   ██╗██╗     ██╗   ██╗ █████╗%b\n' "$red" "$reset"
  printf '%b ██╔══██╗╚══██╔══╝██║   ██║██║     ╚██╗ ██╔╝██╔══██╗%b\n' "$red" "$reset"
  printf '%b ███████║   ██║   ██║   ██║██║      ╚████╔╝ ███████║%b\n' "$red" "$reset"
  printf '%b ██╔══██║   ██║   ██║   ██║██║       ╚██╔╝  ██╔══██║%b\n' "$red" "$reset"
  printf '%b ██║  ██║   ██║   ╚██████╔╝███████╗   ██║   ██║  ██║%b\n' "$red" "$reset"
  printf '%b ╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚══════╝   ╚═╝   ╚═╝  ╚═╝%b\n' "$red" "$reset"
  printf '\n'
  printf '%b  Memory is now in sleep mode. See you on wake.%b\n\n' "$red" "$reset"
}

