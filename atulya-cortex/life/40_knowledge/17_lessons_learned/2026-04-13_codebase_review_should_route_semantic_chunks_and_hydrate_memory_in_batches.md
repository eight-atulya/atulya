# Codebase Review Should Route Semantic Chunks And Hydrate Memory In Batches

Date: 2026-04-13
Repo: atulya
Area: codebases, ASD, review queue, selective hydration, performance

## Trigger

The ASD-first codebase pipeline correctly separated parsing from memory hydration, but the original approval path still tried to hydrate too much of a snapshot at once.

That showed up in the real operator flow as approval-time failures:

- large codebases produced long-running memory writes
- a single approval action tried to hydrate an entire snapshot
- database timeouts appeared during `Approve Memory Import`

The user expectation was stronger than "approve the repo." They wanted a meaningful review queue where only the high-value code should move into memory.

## Root Cause

The bottleneck was not ASD parsing. The bottleneck was the approval unit.

Hydrating memory at the file or snapshot level creates two problems:

- the review surface is too coarse for operators
- the write transaction is too large for production-scale repositories

That means even a correct parse-first pipeline can still fail operationally if approval is treated as a bulk publish step.

## Better System Design

After ASD parsing, the system should create semantic chunks as the primary review unit:

1. parse the repo mechanically
2. derive stable chunk identities from symbols, module regions, and deterministic fallbacks
3. let operators route each chunk to `memory`, `research`, or `dismissed`
4. hydrate only `memory`-routed chunks
5. run hydration in small batches with reuse for unchanged chunks

This preserves mechanical truth in ASD while making the memory layer selective and production-safe.

## Applied Pattern

The production-safe rollout used:

- `codebase_chunks`, `codebase_chunk_edges`, and `codebase_review_routes`
- ASD-derived semantic chunks instead of raw whole-file approval
- cursor-paginated review APIs for large repositories
- chunk-level route inheritance across refreshes using stable keys plus content hashes
- batched memory hydration that reuses unchanged chunks and prunes stale approved items
- control-plane dialogs for deep inspection instead of loading all detail into the first screen

Embeddings were useful only for clustering and related-chunk ranking. They were not allowed to replace parser truth for symbols, imports, or references.

## Practical Rule

If a codebase feature needs human review before memory publish, the review unit should be semantically meaningful and smaller than the whole snapshot.

Use:

- chunk-first review
- selective routing
- short hydration batches

Avoid:

- full-snapshot approval writes
- long single transactions
- forcing operators to approve noise together with the important code

## Validation Rule

For large-repo codebase rollouts, prove all of the following:

- import creates a reviewable snapshot without hydrating memory
- routing changes only the targeted review items
- approval hydrates only `memory`-routed chunks
- unchanged approved chunks are reused on later approval passes
- removed or de-routed chunks are pruned from memory
- review and research APIs stay responsive under pagination
- refresh can inherit prior routes for unchanged chunk identities

Do not treat the feature as production-ready if approval still depends on one large transaction.

## Expected Benefits

- approval is faster and safer on large repositories
- operators can curate only high-value code into memory
- recall and reflect stay cleaner because low-signal code is easier to exclude
- UI stays responsive because review data loads progressively
- ASD remains the source of truth while embeddings add ranking value without compromising determinism

## Cortex Links

- Prior lesson: [Codebase Intelligence Should Parse First And Hydrate Memory Only After Human Approval](./2026-04-12_codebase_intelligence_should_parse_first_and_hydrate_memory_only_after_human_approval.md)
- Root brain contract: [BRAIN.md](../../../../../BRAIN.md)
