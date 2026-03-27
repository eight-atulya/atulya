#!/bin/bash
set -Eeuo pipefail

LIFECYCLE_COMPONENT="docker-start"
SHUTDOWN_TIMEOUT="${ATULYA_SHUTDOWN_TIMEOUT:-10}"

CHILD_PIDS=()
CHILD_NAMES=()

log() {
    local level="$1"
    local event="$2"
    local message="$3"
    printf '%s [%s] [%s] [%s] %s\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$level" "$LIFECYCLE_COMPONENT" "$event" "$message"
}

log_info() { log "INFO" "$1" "$2"; }
log_warn() { log "WARN" "$1" "$2"; }
log_error() { log "ERROR" "$1" "$2"; }

register_child() {
    local name="$1"
    local pid="$2"
    CHILD_NAMES+=("$name")
    CHILD_PIDS+=("$pid")
    log_info "process.register" "Registered child '$name' pid=$pid"
}

is_pid_running() {
    kill -0 "$1" >/dev/null 2>&1
}

terminate_pid_tree() {
    local pid="$1"
    local children
    children=$(pgrep -P "$pid" 2>/dev/null) || true
    local child
    for child in $children; do
        terminate_pid_tree "$child"
    done
    kill "$pid" 2>/dev/null || true
}

shutdown_children() {
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
            terminate_pid_tree "$pid"
        fi
    done

    local elapsed=0
    while [ "$elapsed" -lt "$SHUTDOWN_TIMEOUT" ]; do
        local all_stopped=true
        for pid in "${CHILD_PIDS[@]}"; do
            if is_pid_running "$pid"; then
                all_stopped=false
                break
            fi
        done
        if [ "$all_stopped" = true ]; then
            log_info "shutdown.complete" "All children stopped gracefully"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    log_warn "shutdown.escalate" "Graceful timeout reached; forcing remaining children"
    for pid in "${CHILD_PIDS[@]}"; do
        if is_pid_running "$pid"; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
    log_info "shutdown.complete" "Forced shutdown completed"
}

on_signal() {
    log_warn "shutdown.signal_received" "Signal received, shutting down"
    shutdown_children
    exit 0
}

trap on_signal INT TERM
trap shutdown_children EXIT

# Service flags (default to true if not set)
ENABLE_API="${ATULYA_ENABLE_API:-true}"
ENABLE_CP="${ATULYA_ENABLE_CP:-true}"

# =============================================================================
# Dependency waiting (opt-in via ATULYA_WAIT_FOR_DEPS=true)
#
# Problem: When running with LM Studio, the LLM may take time to load models.
# If Atulya starts before LM Studio is ready, it fails on LLM verification.
# This wait loop ensures dependencies are ready before starting.
# =============================================================================
if [ "${ATULYA_WAIT_FOR_DEPS:-false}" = "true" ]; then
    LLM_BASE_URL="${ATULYA_API_LLM_BASE_URL:-http://host.docker.internal:1234/v1}"
    MAX_RETRIES="${ATULYA_RETRY_MAX:-0}"  # 0 = infinite
    RETRY_INTERVAL="${ATULYA_RETRY_INTERVAL:-10}"

    # Check if external database is configured (skip check for embedded pg0)
    SKIP_DB_CHECK=false
    if [ -z "${ATULYA_API_DATABASE_URL}" ]; then
        SKIP_DB_CHECK=true
    else
        DB_CHECK_HOST=$(echo "$ATULYA_API_DATABASE_URL" | sed -E 's|.*@([^:/]+):([0-9]+)/.*|\1 \2|')
    fi

    check_db() {
        if $SKIP_DB_CHECK; then
            return 0
        fi
        if command -v pg_isready &> /dev/null; then
            pg_isready -h $(echo $DB_CHECK_HOST | cut -d' ' -f1) -p $(echo $DB_CHECK_HOST | cut -d' ' -f2) &>/dev/null
        else
            python3 -c "import socket; s=socket.socket(); s.settimeout(5); exit(0 if s.connect_ex(('$(echo $DB_CHECK_HOST | cut -d' ' -f1)', $(echo $DB_CHECK_HOST | cut -d' ' -f2))) == 0 else 1)" 2>/dev/null
        fi
    }

    check_llm() {
        curl -sf "${LLM_BASE_URL}/models" --connect-timeout 5 &>/dev/null
    }

    log_info "deps.wait_start" "Waiting for dependencies to be ready"
    attempt=1

    while true; do
        db_ok=false
        llm_ok=false

        if check_db; then
            db_ok=true
        fi

        if check_llm; then
            llm_ok=true
        fi

        if $db_ok && $llm_ok; then
            log_info "deps.ready" "Dependencies are ready"
            break
        fi

        if [ "$MAX_RETRIES" -ne 0 ] && [ "$attempt" -ge "$MAX_RETRIES" ]; then
            log_error "deps.timeout" "Max retries ($MAX_RETRIES) reached; dependencies unavailable"
            exit 1
        fi

        log_info "deps.waiting" "Attempt $attempt: DB=$( $db_ok && echo 'ok' || echo 'waiting' ) LLM=$( $llm_ok && echo 'ok' || echo 'waiting' )"
        sleep "$RETRY_INTERVAL"
        ((attempt++))
    done
fi

# Start API if enabled
if [ "$ENABLE_API" = "true" ]; then
    cd /app/api
    log_info "startup.api" "Starting API service"
    atulya-api &
    API_PID=$!
    register_child "api" "$API_PID"

    # Wait for API to be ready
    API_READY=false
    for i in {1..120}; do
        if curl -sf http://localhost:8888/health &>/dev/null; then
            API_READY=true
            log_info "readiness.ready" "API is healthy after ${i}s"
            break
        fi
        if ! is_pid_running "$API_PID"; then
            log_error "readiness.child_crash" "API process exited before readiness"
            exit 31
        fi
        sleep 1
    done
    if [ "$API_READY" = false ]; then
        log_error "readiness.timeout" "API did not become healthy in time"
        exit 21
    fi
else
    log_info "startup.api_skipped" "API disabled (ATULYA_ENABLE_API=false)"
fi

# Start Control Plane if enabled
if [ "$ENABLE_CP" = "true" ]; then
    log_info "startup.control_plane" "Starting Control Plane"
    cd /app/control-plane
    PORT="${ATULYA_CP_PORT:-9999}" node server.js &
    CP_PID=$!
    register_child "control-plane" "$CP_PID"
else
    log_info "startup.cp_skipped" "Control Plane disabled (ATULYA_ENABLE_CP=false)"
fi

# Print status
log_info "startup.ready" "Atulya runtime is up"
if [ "$ENABLE_CP" = "true" ]; then
    log_info "startup.endpoint" "Control Plane: http://localhost:${ATULYA_CP_PORT:-9999}"
fi
if [ "$ENABLE_API" = "true" ]; then
    log_info "startup.endpoint" "API: http://localhost:8888"
fi

# Check if any services are running
if [ ${#CHILD_PIDS[@]} -eq 0 ]; then
    log_error "preflight.no_services" "No services enabled; set ATULYA_ENABLE_API=true or ATULYA_ENABLE_CP=true"
    exit 1
fi

while true; do
    for i in "${!CHILD_PIDS[@]}"; do
        pid="${CHILD_PIDS[$i]}"
        name="${CHILD_NAMES[$i]}"
        if ! is_pid_running "$pid"; then
            log_error "process.exited" "Child '$name' exited unexpectedly (pid=$pid)"
            exit 31
        fi
    done
    sleep 2
done
