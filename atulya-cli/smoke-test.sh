#!/bin/bash
# CLI smoke test - verifies basic CLI functionality against a running API server
#
# Prerequisites:
#   - atulya CLI must be in PATH or ATULYA_CLI env var set
#   - API server must be running at ATULYA_API_URL (default: http://localhost:8888)
#
# Usage:
#   ./atulya-cli/smoke-test.sh
#   ATULYA_CLI=/path/to/atulya ./atulya-cli/smoke-test.sh

set -e

# Configuration
ATULYA_CLI="${ATULYA_CLI:-atulya}"
export ATULYA_API_URL="${ATULYA_API_URL:-http://localhost:8888}"
TEST_BANK="cli-smoke-test-$(date +%s)"

echo "=== Atulya CLI Smoke Test ==="
echo "CLI: $ATULYA_CLI"
echo "API URL: $ATULYA_API_URL"
echo "Test bank: $TEST_BANK"
echo ""

# Helper function
run_test() {
    local name="$1"
    shift
    echo -n "Testing: $name... "
    if "$@" > /tmp/cli-test-output.txt 2>&1; then
        echo "OK"
        return 0
    else
        echo "FAILED"
        echo "  Command: $*"
        echo "  Output:"
        cat /tmp/cli-test-output.txt | sed 's/^/    /'
        return 1
    fi
}

run_test_output() {
    local name="$1"
    local expected="$2"
    shift 2
    echo -n "Testing: $name... "
    if "$@" > /tmp/cli-test-output.txt 2>&1; then
        if grep -qi "$expected" /tmp/cli-test-output.txt; then
            echo "OK"
            return 0
        else
            echo "FAILED (expected '$expected' not found)"
            echo "  Command: $*"
            echo "  Output:"
            cat /tmp/cli-test-output.txt | sed 's/^/    /'
            return 1
        fi
    else
        echo "FAILED"
        echo "  Command: $*"
        echo "  Output:"
        cat /tmp/cli-test-output.txt | sed 's/^/    /'
        return 1
    fi
}

cleanup() {
    echo ""
    echo "Cleaning up test bank..."
    "$ATULYA_CLI" bank delete "$TEST_BANK" -y 2>/dev/null || true
}
trap cleanup EXIT

FAILED=0

# Test 1: Version
run_test "version" "$ATULYA_CLI" --version || FAILED=1

# Test 2: Help
run_test "help" "$ATULYA_CLI" --help || FAILED=1

# Test 3: Configure help
run_test "configure help" "$ATULYA_CLI" configure --help || FAILED=1

# Test 4: List banks (JSON output)
run_test "list banks" "$ATULYA_CLI" bank list -o json || FAILED=1

# Test 5: Set bank name (creates the bank)
run_test "set bank name" "$ATULYA_CLI" bank name "$TEST_BANK" "CLI Smoke Test Bank" || FAILED=1

# Test 6: Get bank disposition
run_test_output "get bank disposition" "CLI Smoke Test Bank" "$ATULYA_CLI" bank disposition "$TEST_BANK" || FAILED=1

# Test 7: Retain memory
run_test "retain memory" "$ATULYA_CLI" memory retain "$TEST_BANK" "Alice is a software engineer who loves Rust programming" || FAILED=1

# Test 8: Retain more memories
run_test "retain more memories" "$ATULYA_CLI" memory retain "$TEST_BANK" "Bob is Alice's colleague who prefers Python" || FAILED=1

# Test 9: Recall memories
run_test_output "recall memories" "Alice" "$ATULYA_CLI" memory recall "$TEST_BANK" "Who is Alice?" || FAILED=1

# Test 10: Reflect on memories
run_test_output "reflect" "Alice" "$ATULYA_CLI" memory reflect "$TEST_BANK" "What do you know about Alice?" || FAILED=1

# Test 11: Get bank stats
run_test "bank stats" "$ATULYA_CLI" bank stats "$TEST_BANK" || FAILED=1

# Test 12: List entities
run_test "list entities" "$ATULYA_CLI" entity list "$TEST_BANK" || FAILED=1

# Test 13: List documents
run_test "list documents" "$ATULYA_CLI" document list "$TEST_BANK" || FAILED=1

# Test 14: Clear memories
run_test "clear memories" "$ATULYA_CLI" memory clear "$TEST_BANK" || FAILED=1

# Test 15: List operations
run_test "list operations" "$ATULYA_CLI" operation list "$TEST_BANK" || FAILED=1

# Test 16: Delete bank
run_test "delete bank" "$ATULYA_CLI" bank delete "$TEST_BANK" -y || FAILED=1

echo ""
if [ $FAILED -eq 0 ]; then
    echo "=== All smoke tests passed! ==="
    exit 0
else
    echo "=== Some smoke tests failed ==="
    exit 1
fi
