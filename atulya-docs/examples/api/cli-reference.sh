#!/bin/bash
# CLI Reference examples for Atulya
# Tests all documented CLI commands and flags
# Run: bash examples/api/cli-reference.sh

set -e

ATULYA_URL="${ATULYA_API_URL:-http://localhost:8888}"
BANK_ID="cli-test-bank"
DOC_ID="test-document-001"

# =============================================================================
# Setup
# =============================================================================
atulya configure --api-url "$ATULYA_URL"

# Create test data with a known document ID
atulya memory retain "$BANK_ID" "Alice works at Google as a software engineer" --doc-id "$DOC_ID"
atulya memory retain "$BANK_ID" "Bob is a data scientist who collaborates with Alice" --doc-id "$DOC_ID"
atulya memory retain "$BANK_ID" "Alice and Bob work on machine learning projects"
# Create document for delete test early so it has time to index
atulya memory retain "$BANK_ID" "Carol is a project manager who coordinates the engineering team" --doc-id "temp-doc-to-delete"

# Wait for memories to be indexed (LLM processing takes time)
sleep 5

# =============================================================================
# Configuration (cli.md - Configuration section)
# =============================================================================

# [docs:cli-configure]
atulya configure --api-url http://localhost:8888
# [/docs:cli-configure]


# =============================================================================
# Core Memory Commands (cli.md - Core Commands section)
# =============================================================================

# [docs:cli-retain-basic]
atulya memory retain $BANK_ID "Alice works at Google as a software engineer"
# [/docs:cli-retain-basic]


# [docs:cli-retain-context]
atulya memory retain $BANK_ID "Bob loves hiking" --context "hobby discussion"
# [/docs:cli-retain-context]


# [docs:cli-retain-async]
atulya memory retain $BANK_ID "Meeting notes" --async
# [/docs:cli-retain-async]


# [docs:cli-recall-basic]
atulya memory recall $BANK_ID "What does Alice do?"
# [/docs:cli-recall-basic]


# [docs:cli-recall-options]
atulya memory recall $BANK_ID "hiking recommendations" \
  --budget high \
  --max-tokens 8192
# [/docs:cli-recall-options]


# [docs:cli-recall-fact-type]
atulya memory recall $BANK_ID "query" --fact-type world,opinion
# [/docs:cli-recall-fact-type]


# [docs:cli-recall-trace]
atulya memory recall $BANK_ID "query" --trace
# [/docs:cli-recall-trace]


# [docs:cli-reflect-basic]
atulya memory reflect $BANK_ID "What do you know about Alice?"
# [/docs:cli-reflect-basic]


# [docs:cli-reflect-context]
atulya memory reflect $BANK_ID "Should I learn Python?" --context "career advice"
# [/docs:cli-reflect-context]


# [docs:cli-reflect-budget]
atulya memory reflect $BANK_ID "Summarize my week" --budget high
# [/docs:cli-reflect-budget]


# =============================================================================
# Bank Management (cli.md - Bank Management section)
# =============================================================================

# [docs:cli-bank-list]
atulya bank list
# [/docs:cli-bank-list]


# [docs:cli-bank-disposition]
atulya bank disposition $BANK_ID
# [/docs:cli-bank-disposition]


# [docs:cli-bank-stats]
atulya bank stats $BANK_ID
# [/docs:cli-bank-stats]


# [docs:cli-bank-name]
atulya bank name $BANK_ID "My Assistant"
# [/docs:cli-bank-name]


# [docs:cli-bank-background]
atulya bank background $BANK_ID "I am a helpful AI assistant interested in technology"
# [/docs:cli-bank-background]


# [docs:cli-bank-background-no-disposition]
atulya bank background $BANK_ID "Background text" --no-update-disposition
# [/docs:cli-bank-background-no-disposition]


# =============================================================================
# Document Management (cli.md - Document Management section)
# =============================================================================

# [docs:cli-document-list]
atulya document list $BANK_ID
# [/docs:cli-document-list]


# [docs:cli-document-get]
atulya document get $BANK_ID $DOC_ID
# [/docs:cli-document-get]


# [docs:cli-document-delete]
atulya document delete $BANK_ID temp-doc-to-delete
# [/docs:cli-document-delete]


# =============================================================================
# Entity Management (cli.md - Entity Management section)
# =============================================================================

# [docs:cli-entity-list]
atulya entity list $BANK_ID
# [/docs:cli-entity-list]


# Get an entity ID from the list output and use it
ENTITY_ID=$(atulya entity list $BANK_ID -o json 2>/dev/null | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4 || echo "")

if [ -n "$ENTITY_ID" ]; then
    # [docs:cli-entity-get]
    atulya entity get $BANK_ID $ENTITY_ID
    # [/docs:cli-entity-get]

    # [docs:cli-entity-regenerate]
    atulya entity regenerate $BANK_ID $ENTITY_ID
    # [/docs:cli-entity-regenerate]
else
    echo "No entities found yet, skipping entity get/regenerate"
fi


# =============================================================================
# Output Formats (cli.md - Output Formats section)
# =============================================================================

# [docs:cli-output-json]
atulya memory recall $BANK_ID "query" -o json
# [/docs:cli-output-json]


# [docs:cli-output-yaml]
atulya memory recall $BANK_ID "query" -o yaml
# [/docs:cli-output-yaml]


# =============================================================================
# Global Options (cli.md - Global Options section)
# =============================================================================

# [docs:cli-verbose]
atulya memory recall $BANK_ID "Alice" -v
# [/docs:cli-verbose]


# [docs:cli-help]
atulya --help
# [/docs:cli-help]


# [docs:cli-version]
atulya --version
# [/docs:cli-version]


# =============================================================================
# Cleanup
# =============================================================================
curl -s -X DELETE "${ATULYA_URL}/v1/default/banks/${BANK_ID}" > /dev/null

echo "cli-reference.sh: All examples passed"
