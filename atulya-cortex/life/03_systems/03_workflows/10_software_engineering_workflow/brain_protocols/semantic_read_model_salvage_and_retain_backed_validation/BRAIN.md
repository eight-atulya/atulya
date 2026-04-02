---
name: semantic_read_model_salvage_and_retain_backed_validation
description: Use when a semantic or graph-heavy read-model rewrite fixes a compelling real example but risks breaking the existing subsystem contract. Covers salvage-first implementation, retain-backed evaluation, publish hygiene, and Cortex learning capture.
kind: brain_protocol
---

# Semantic Read Model Salvage And Retain Backed Validation

## Purpose
This protocol helps recover a semantic read-model rewrite when the idea is promising but the current patch is too risky to trust.

The goal is to keep the insight, discard the unsafe shape, and prove the rebuilt behavior through both deterministic tests and a tiny real-system retain corpus.

## Use This Protocol When

- a graph, ranking, contradiction, clustering, or state-detection rewrite improves one real case but breaks broader behavior
- synthetic tests alone are not enough to judge whether the smarter logic helps in practice
- a semantic subsystem needs both contract protection and lightweight real-world evaluation
- the publish flow should capture the reasoning chain and the learned workflow in Cortex

## Do Not Use This Protocol When

- the issue is a narrow bug fix with no semantic or heuristic redesign
- the system has no reliable contract tests to preserve
- the real-system validation path is too expensive to run even as a tiny curated corpus

## Core Principles

- Preserve the old contract before expanding the new heuristics.
- Treat a rewrite as a source of ideas, not automatically as the new baseline.
- Keep deterministic tests for exact invariants and add a tiny retain-backed lane for realism.
- Validate the exact operator-facing path before publish.
- Capture both the lesson and the command trail in Cortex so future debugging starts from memory, not from scratch.

## Mental Model

Semantic read models have at least four layers:

1. local logic rules such as contradiction gating, ownership, dedup, and event identity
2. heuristic surfaces such as cosine thresholds, clustering, and temporal guards
3. end-to-end retain behavior such as extraction, entities, timestamps, chunk IDs, and embeddings
4. publish hygiene such as tests, hooks, staged scope, and commit strategy

Most regressions happen when one layer is improved in isolation and the contract across the other layers is not re-proven.

## Execution Flow

### 1. Reconstruct The Behavioral Contract

Run the existing targeted test file first and identify whether the current failure is:

- logic regression
- threshold calibration problem
- missing-realism problem
- or publish / environment confusion

Do not tune embeddings or thresholds before the contract failures are understood.

### 2. Separate The Valuable Insight From The Unsafe Rewrite

Map the rewrite into two buckets:

- worth keeping, such as ownership guards, same-document suppression, dedup, or better event ranking
- not safe yet, such as hard embedding gates, cluster-driven early returns, or large threshold swings

Keep the ideas. Rebuild the implementation incrementally.

### 3. Restore Stable Semantics First

Re-establish the last known-good invariants:

- contradictions still surface even if clustering collapses facts into one semantic state
- missing embeddings do not erase otherwise valid changes
- multi-step timelines emit unique event IDs
- public API shapes remain unchanged

### 4. Add A Tiny Real Retain Corpus

Build a tiny retain-driven evaluation lane with only a few tricky scenarios:

- true contradiction
- true state change
- semantic duplicate
- ownership / cross-mention trap

Keep it small enough for local models and normal developer iteration.

### 5. Validate The Important Paths

Run:

- targeted lint and format checks
- the full subsystem test file
- the tiny retain-backed evaluation lane

If the complaint involved commit / hook behavior, verify the publish path too.

### 6. Publish Intentionally

Stage only the scoped files.
If hooks mutate files during commit, expect a possible post-commit formatter cleanup and handle it as a tiny follow-up commit rather than mixing it into the logic patch blindly.

### 7. Persist The Cortex Memory

Capture three layers:

- lesson learned in `40_knowledge/17_lessons_learned`
- reusable workflow in `03_systems/03_workflows/10_software_engineering_workflow/brain_protocols`
- incident command / event trail in the protocol references

## Output Contract

A successful run should leave behind:

- a safer semantic implementation
- deterministic contract tests that pass
- a tiny real retain corpus that passes
- meaningful commits with scoped validation
- Cortex memory that explains both the why and the exact command trail

## Decision Guardrails

- Do not widen thresholds in production just because one debug case looks better.
- Do not require embeddings for logic that must still work without them.
- Do not let clustering short-circuit contradiction scans across distinct facts.
- Do not treat one offline trace as enough proof for a semantic subsystem.
- Do not publish without capturing the reusable workflow if the incident taught one.

## Common Failure Modes

- fixing only the debug example and missing contract regressions elsewhere
- replacing stable text/time fallbacks with hard embedding dependence
- leaving unique-event bugs hidden behind dict lookups or downstream collapsing
- building a realistic eval lane that is so slow nobody reruns it
- letting auto-format hooks mutate files after commit without noticing

## References

- Command patterns and captured session trail: [references/command_patterns.md](./references/command_patterns.md)
- Incident timeline: [references/incident_timeline_2026_04_02_graph_intelligence.md](./references/incident_timeline_2026_04_02_graph_intelligence.md)
- Repo lesson: [../../../../../40_knowledge/17_lessons_learned/2026-04-02_graph_intelligence_semantic_rewrites_need_contract_tests_and_real_retain_corpus.md](../../../../../40_knowledge/17_lessons_learned/2026-04-02_graph_intelligence_semantic_rewrites_need_contract_tests_and_real_retain_corpus.md)
