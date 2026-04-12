# Codebase Intelligence Should Parse First And Hydrate Memory Only After Human Approval

Date: 2026-04-12
Repo: atulya
Area: codebases, ASD, tree-sitter, memory hydration, control plane

## Trigger

Issue `#19` started as a codebase-import and deterministic code-intelligence feature, but the initial implementation direction still treated automatic memory hydration as part of the import path.

That created a mismatch with the ASD comments and with the operational reality of Atulya memory:

- ASD is supposed to be the mechanical code-intelligence subsystem
- memory hydration is heavier and changes what `recall` and `reflect` can see
- operators need a chance to review a parsed snapshot before that memory state mutates

## Root Cause

The problem was not that deterministic parsing was weak. The problem was coupling two different responsibilities:

- code intelligence publish
- memory publish

If those happen in one step, a repo import silently becomes a memory mutation, even when the operator has not reviewed the parsed snapshot yet.

That is the wrong contract for codebases because the developer wants immediate structural understanding, but they may not yet trust the snapshot enough to let it shape memory-backed reasoning.

## Better System Design

For codebase ingestion in Atulya:

1. import the archive
2. run ASD mechanical parsing first
3. publish a reviewable snapshot immediately for file map, symbols, and impact
4. require explicit human approval before hydrating source-file text into memory
5. keep the last approved snapshot as the active memory source until the new one is approved

The key separation is:

- `current_snapshot_id` powers code intelligence
- `approved_snapshot_id` powers memory-backed flows

That lets the system move fast without letting every import mutate shared reasoning state.

## Applied Pattern

The shipped implementation used:

- an ASD-first parser/indexer layer backed by `tree-sitter`
- deterministic snapshot statuses like `review_required`
- explicit `approve` operations for memory hydration
- stable codebase document IDs of the form `codebase:{codebase_id}:{path}`
- refresh behavior where GitHub snapshots can update code intelligence first while memory stays on the previously approved snapshot

This produced a cleaner operator contract:

- import and refresh are cheap, reviewable, and mechanical
- memory growth is deliberate
- `files`, `symbols`, and `impact` stay immediately useful
- `recall` and `reflect` stay tied to approved source state

## Practical Rule

If a feature extracts structure from source code and also wants to reuse Atulya memory, do not assume both concerns belong in the same publish step.

Use this split:

- mechanical parse first
- explicit approval second
- memory hydration last

This is especially important when:

- the parser is deterministic
- the memory layer is LLM-heavy
- the imported source may be large, noisy, or untrusted
- the UI needs a review step before shared state changes

## Validation Rule

When shipping changes to the codebase pipeline:

- test the review-required state after import
- test that `files`, `symbols`, and `impact` work before approval
- test that no codebase document exists before approval
- test that approval hydrates changed files and deletes removed-file documents
- test that refresh with no remote change returns `noop`
- test that a new parsed snapshot can coexist with memory still pointing to the last approved snapshot

Do not call the rollout complete if only the parse path works. The approval boundary is part of the contract.

## Expected Benefits

- code intelligence stays fast and deterministic
- memory-backed reasoning stays deliberate and auditable
- operators can trust that new snapshots do not silently rewrite bank memory
- refresh workflows become safer for high-churn repositories
- the control plane can present a clearer developer review loop

## Cortex Links

- Root brain contract: [BRAIN.md](../../../../../BRAIN.md)
- Related lesson style: [Graph Intelligence Semantic Rewrites Need Contract Tests And A Tiny Real-Retain Corpus](./2026-04-02_graph_intelligence_semantic_rewrites_need_contract_tests_and_real_retain_corpus.md)
