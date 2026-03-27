#!/bin/bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lifecycle.sh"

LIFECYCLE_COMPONENT="build-brain"
ROOT_DIR="$(project_root_from_dev_script)"
cd "$ROOT_DIR"

BRAIN_DIR="$ROOT_DIR/atulya-brain"

if [ ! -d "$BRAIN_DIR" ]; then
  fail_with 10 "preflight.missing_dir" "atulya-brain directory not found at $BRAIN_DIR"
fi

if ! command -v cargo >/dev/null 2>&1; then
  fail_with 12 "preflight.command_missing" "cargo not found. Install Rust toolchain (rustup/cargo) to build native atulya-brain."
fi

log_info "build.start" "Building atulya-brain native library (release)"
cargo build --release --manifest-path "$BRAIN_DIR/Cargo.toml"

case "$(uname -s)" in
Darwin)
  LIB_PATH="$BRAIN_DIR/target/release/libatulya_brain.dylib"
  ;;
Linux)
  LIB_PATH="$BRAIN_DIR/target/release/libatulya_brain.so"
  ;;
MINGW*|MSYS*|CYGWIN*)
  LIB_PATH="$BRAIN_DIR/target/release/atulya_brain.dll"
  ;;
*)
  fail_with 10 "preflight.unsupported_os" "Unsupported OS for automatic brain library path resolution"
  ;;
esac

if [ ! -f "$LIB_PATH" ]; then
  fail_with 21 "build.artifact_missing" "Build completed but native library was not found at $LIB_PATH"
fi

log_info "build.success" "Native library ready at $LIB_PATH"
echo ""
echo "Export this before starting API:"
echo "  export ATULYA_API_BRAIN_NATIVE_LIBRARY_PATH=\"$LIB_PATH\""

