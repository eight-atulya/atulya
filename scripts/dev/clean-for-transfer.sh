#!/usr/bin/env bash
# =============================================================================
# clean-for-transfer.sh
# Purpose : Recursively remove build artifacts + caches before zip/transfer.
# Usage   : ./scripts/dev/clean-for-transfer.sh [TARGET_DIR] [--remove-lockfiles]
#           TARGET_DIR defaults to workspace root (two levels up from script).
#           Lockfiles are preserved by default to keep transferred repos reproducible.
# =============================================================================

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_TARGET_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
TARGET_DIR="$DEFAULT_TARGET_DIR"
REMOVE_LOCKFILES=false

usage() {
  cat <<'EOF'
Usage: ./scripts/dev/clean-for-transfer.sh [TARGET_DIR] [--remove-lockfiles]

Arguments:
  TARGET_DIR            Directory to clean. Defaults to the repo root.
  --remove-lockfiles    Also remove dependency lockfiles such as uv.lock,
                        Cargo.lock, and Chart.lock.
  -h, --help            Show this help message.
EOF
}

# Directories to nuke (exact folder name match, recursive)
DIRS_TO_REMOVE=(
  "node_modules"
  ".next"
  ".nuxt"
  ".vite"
  "dist"
  "build"
  "__pycache__"
  ".pytest_cache"
  ".mypy_cache"
  ".ruff_cache"
  ".tox"
  ".eggs"
  "*.egg-info"
  ".turbo"
  ".parcel-cache"
  ".cache"
  ".venv"
  "venv"
  ".serverless"
  "coverage"
  ".nyc_output"
  ".gradle"
  "target"          # Maven/Rust
)

# Files to nuke
FILES_TO_REMOVE=(
  "*.pyc"
  "*.pyo"
  "*.pyd"
  ".DS_Store"
  "Thumbs.db"
  "*.log"
)

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { printf "[INFO]  %s\n" "$*"; }
warn() { printf "[WARN]  %s\n" "$*"; }
ok()   { printf "[VALID] %s\n" "$*"; }

bytes_freed=0

while (($#)); do
  case "$1" in
    --remove-lockfiles)
      REMOVE_LOCKFILES=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      warn "Unknown flag: $1"
      usage
      exit 1
      ;;
    *)
      if [[ "$TARGET_DIR" != "$DEFAULT_TARGET_DIR" ]]; then
        warn "Only one target directory may be provided"
        usage
        exit 1
      fi
      TARGET_DIR="$1"
      shift
      ;;
  esac
done

remove_dirs() {
  local pattern="$1"
  # -prune prevents descending into already-found node_modules trees
  while IFS= read -r -d '' dir; do
    local size
    size=$(du -sk "$dir" 2>/dev/null | awk '{print $1}')
    bytes_freed=$(( bytes_freed + size ))
    rm -rf "$dir"
    log "removed dir  → $dir  (${size}K)"
  done < <(find "$TARGET_DIR" \
    -type d -name "$pattern" \
    -not -path "*/.git/*" \
    -print0 2>/dev/null)
}

remove_files() {
  local pattern="$1"
  while IFS= read -r -d '' f; do
    rm -f "$f"
  done < <(find "$TARGET_DIR" \
    -type f -name "$pattern" \
    -not -path "*/.git/*" \
    -print0 2>/dev/null)
}

# ── Guard ─────────────────────────────────────────────────────────────────────
if [[ ! -d "$TARGET_DIR" ]]; then
  warn "Target directory not found: $TARGET_DIR"
  exit 1
fi

log "Target : $TARGET_DIR"
if [[ "$REMOVE_LOCKFILES" == true ]]; then
  warn "Lockfile removal enabled; dependency lockfiles will be deleted"
else
  log "Preserving dependency lockfiles for reproducible installs"
fi
log "Starting clean …"
echo "────────────────────────────────────────────────────"

# ── Nuke dirs ─────────────────────────────────────────────────────────────────
for pattern in "${DIRS_TO_REMOVE[@]}"; do
  remove_dirs "$pattern"
done

# ── Nuke files ────────────────────────────────────────────────────────────────
for pattern in "${FILES_TO_REMOVE[@]}"; do
  remove_files "$pattern"
done

if [[ "$REMOVE_LOCKFILES" == true ]]; then
  remove_files "*.lock"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo "────────────────────────────────────────────────────"
ok "Clean complete. ~${bytes_freed}K freed from $TARGET_DIR"
log "Directory is ready for zip / transfer."
