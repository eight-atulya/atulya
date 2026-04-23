#!/usr/bin/env bash
set -euo pipefail

# attention_network_local_test.sh
# End-to-end smoke test for the attention network utilities.
#
# What this script checks:
# 1) Local model host reachability at localhost:1234 (/v1/models)
# 2) Structured JSON response generation from /v1/chat/completions
# 3) IP -> binary persistence + BRAIN.md metadata hashing
# 4) Deterministic routing over 8 attention categories
#
# Guardrail / limitation notes:
# - This is a transport-level and schema-level smoke test, not a security proof.
# - "Jailbreak resistance" is partial by design here; we only assert structured
#   output shape and deterministic routing behavior.
# - Strong prompt-injection hardening should be implemented at policy/middleware
#   level in the caller before tool execution.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${ROOT_DIR}/.tmp_attention_network"
mkdir -p "${WORK_DIR}"

BRAIN_MD="${ROOT_DIR}/../BRAIN.md"
IP_BIN="${WORK_DIR}/host_ip.bin"
ENTITIES_JSON="${WORK_DIR}/entities.json"

cat > "${ENTITIES_JSON}" <<'EOF'
[
  {"entity_id":"mem-1","category":"memory","semantic_relevance":0.95,"recency":0.80,"task_alignment":0.90,"user_intent":0.80,"system_state":0.60},
  {"entity_id":"tool-1","category":"tool","semantic_relevance":0.90,"recency":0.60,"task_alignment":0.92,"user_intent":0.82,"system_state":0.80},
  {"entity_id":"agent-1","category":"agent","semantic_relevance":0.85,"recency":0.50,"task_alignment":0.95,"user_intent":0.75,"system_state":0.70},
  {"entity_id":"task-1","category":"task","semantic_relevance":0.88,"recency":0.90,"task_alignment":0.96,"user_intent":0.85,"system_state":0.88},
  {"entity_id":"intent-1","category":"user_intent","semantic_relevance":0.99,"recency":0.70,"task_alignment":0.80,"user_intent":1.00,"system_state":0.60},
  {"entity_id":"state-1","category":"system_state","semantic_relevance":0.72,"recency":0.95,"task_alignment":0.75,"user_intent":0.60,"system_state":1.00},
  {"entity_id":"input-1","category":"input_context","semantic_relevance":0.77,"recency":0.40,"task_alignment":0.82,"user_intent":0.88,"system_state":0.72},
  {"entity_id":"output-1","category":"output_context","semantic_relevance":0.80,"recency":0.30,"task_alignment":0.81,"user_intent":0.70,"system_state":0.65}
]
EOF

echo "[1/4] Ping local model server..."
uv run python plasticity/attention_network.py ping-model --base-url "http://127.0.0.1:1234/v1" | tee "${WORK_DIR}/ping.json"

echo "[2/4] Request structured response..."
uv run python plasticity/attention_network.py ask-model \
  --base-url "http://127.0.0.1:1234/v1" \
  --prompt "Return a compact operational recommendation for cortex attention routing." \
  | tee "${WORK_DIR}/structured_response.json"

echo "[3/4] Persist binary IP and hash with BRAIN metadata..."
uv run python plasticity/attention_network.py ip-hash \
  --ip "127.0.0.1" \
  --binary-path "${IP_BIN}" \
  --brain-md "${BRAIN_MD}" \
  | tee "${WORK_DIR}/ip_hash.json"

echo "[4/4] Route entities deterministically..."
uv run python plasticity/attention_network.py route \
  --entities-json "${ENTITIES_JSON}" \
  --per-category-limit 1 \
  --total-limit 8 \
  | tee "${WORK_DIR}/route.json"

echo "Attention-network smoke test complete."
echo "Artifacts: ${WORK_DIR}"

