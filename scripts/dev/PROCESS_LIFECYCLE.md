# Process Lifecycle Contract

This document defines the startup/shutdown behavior for Atulya script entrypoints.

## Scope

- `scripts/dev/start.sh`
- `scripts/dev/start-api.sh`
- `scripts/dev/start-worker.sh`
- `scripts/dev/start-control-plane.sh`
- `scripts/dev/build-brain.sh`
- `scripts/dev/monitoring/start.sh`
- `docker/standalone/start-all.sh`

## Required Behavior

### 1) Strict mode and deterministic failure

- Scripts must run with strict error handling:
  - `set -Eeuo pipefail`
- Scripts must fail early on:
  - missing required commands
  - invalid arguments
  - unavailable required ports (unless caller explicitly controls bind strategy)
  - readiness timeout

### 2) Environment precedence

Environment resolution order is:

1. script defaults
2. `.env` at project root (if present)
3. caller-provided environment variables and CLI flags

This guarantees predictable override behavior across local and CI invocations.

For `atulya-brain`:

- `ATULYA_API_BRAIN_ENABLED=true` enables sub_routine runtime path.
- `ATULYA_API_BRAIN_NATIVE_LIBRARY_PATH` enables native library loading.
- `ATULYA_API_BRAIN_NATIVE_AUTO_BUILD=true` allows startup scripts to build native library when `cargo` is available.
- If native library cannot be loaded, startup continues with Python fallback runtime (non-fatal).

### 3) Readiness gates

- API startup must validate `/health` before dependent services start.
- Dependency waits must include bounded timeout and clear failure reason.
- If a service exits before readiness, startup fails immediately.

### 4) Process supervision

- Parent scripts register each child process by name + PID.
- Parent continuously checks child liveness.
- If any required child exits unexpectedly, parent exits non-zero.

### 5) Graceful shutdown ladder

On `SIGINT`/`SIGTERM`:

1. send `SIGTERM` to child process tree
2. wait up to configured timeout
3. force remaining processes with `SIGKILL`

### 6) Logging contract

All orchestrator scripts emit lifecycle logs in this format:

`[timestamp_utc] [level] [component] [event] message`

Example:

`2026-03-07T16:50:19Z [INFO] [dev-start] [startup.api] Starting API`

### 7) Exit code classes

- `10-19`: argument / preflight validation failures
- `20-29`: readiness/dependency timeout failures
- `30-39`: child process crash/supervision failures

