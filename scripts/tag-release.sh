#!/bin/bash
set -Eeuo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

usage() {
    cat <<'EOF'
Usage: ./scripts/tag-release.sh <version> [--push]

Creates an annotated release tag for a repo that is already versioned.
Runs the v0.8.0 release preflight before tagging.

Examples:
  ./scripts/tag-release.sh 0.8.0
  ./scripts/tag-release.sh 0.8.0 --push
EOF
}

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    usage
    exit 1
fi

VERSION="$1"
PUSH_TAG=false
if [ $# -eq 2 ]; then
    if [ "$2" != "--push" ]; then
        usage
        exit 1
    fi
    PUSH_TAG=true
fi

if ! [[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    print_error "Invalid version format: $VERSION"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PRECHECK_SCRIPT="$SCRIPT_DIR/release-preflight-v0800.sh"

require_clean_worktree() {
    if [[ -n $(git status --short) ]]; then
        print_error "Working directory is not clean. Commit or stash changes before tagging."
        git status --short
        exit 1
    fi
}

require_main_branch() {
    local branch
    branch="$(git branch --show-current)"
    if [ "$branch" != "main" ]; then
        print_error "Tagging is only allowed from main. Current branch: $branch"
        exit 1
    fi
}

assert_tag_absent() {
    if git rev-parse "v$VERSION" >/dev/null 2>&1; then
        print_error "Tag v$VERSION already exists"
        exit 1
    fi
}

assert_manifest_version() {
    local file="$1"
    local pattern="$2"
    local actual
    actual="$(rg -o "$pattern" "$file" | head -n 1 | sed 's/.*\"//; s/\"$//')"
    if [ -z "$actual" ]; then
        actual="$(rg -o "$pattern" "$file" | head -n 1 | sed 's/.*= \"//; s/\"$//')"
    fi
    if [ "$actual" != "$VERSION" ]; then
        print_error "Version mismatch in $file: expected $VERSION, found ${actual:-<missing>}"
        exit 1
    fi
}

assert_versions_match() {
    assert_manifest_version "$ROOT_DIR/atulya-api/pyproject.toml" '^version = "[^"]+"'
    assert_manifest_version "$ROOT_DIR/atulya/pyproject.toml" '^version = "[^"]+"'
    assert_manifest_version "$ROOT_DIR/atulya-clients/python/pyproject.toml" '^version = "[^"]+"'
    assert_manifest_version "$ROOT_DIR/atulya-cli/Cargo.toml" '^version = "[^"]+"'
    assert_manifest_version "$ROOT_DIR/atulya-clients/typescript/package.json" '"version": "[^"]+"'
    assert_manifest_version "$ROOT_DIR/atulya-control-plane/package.json" '"version": "[^"]+"'
    assert_manifest_version "$ROOT_DIR/atulya-integrations/openclaw/package.json" '"version": "[^"]+"'
    assert_manifest_version "$ROOT_DIR/atulya-integrations/ai-sdk/package.json" '"version": "[^"]+"'
    assert_manifest_version "$ROOT_DIR/atulya-integrations/chat/package.json" '"version": "[^"]+"'
}

print_info "Preparing annotated tag for v$VERSION"
require_main_branch
require_clean_worktree
assert_tag_absent
assert_versions_match

print_info "Running release preflight"
"$PRECHECK_SCRIPT" "$VERSION"

print_info "Creating tag v$VERSION"
git tag -a "v$VERSION" -m "Release v$VERSION"

if [ "$PUSH_TAG" = true ]; then
    print_info "Pushing tag v$VERSION"
    git push origin "v$VERSION"
else
    print_warn "Tag created locally only. Push when ready with: git push origin v$VERSION"
fi

print_info "Release tag v$VERSION is ready"
