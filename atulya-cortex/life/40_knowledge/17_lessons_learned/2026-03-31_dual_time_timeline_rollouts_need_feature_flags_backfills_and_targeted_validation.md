# Dual-Time Timeline Rollouts Need Feature Flags, Backfills, and Targeted Validation

Date: 2026-03-31
Repo: atulya
Area: memory timeline, temporal semantics, control-plane visualization

## Trigger

The timeline view looked empty or weak for normal memory banks because it only rendered `occurred_start`-anchored memories. Most real memories had recorded time but not explicit event time, so the interface communicated "nothing happened" when data was actually present.

## Root Cause

The product had one implicit notion of time in the UI but at least two real notions in the data:

- semantic event time, when something actually happened
- recorded time, when the system learned or observed it

The old timeline path treated missing semantic time as missing timeline eligibility. That was the wrong abstraction. The real source issue was not just rendering; it was the absence of a normalized temporal layer that could safely represent:

- exact events
- inferred events
- ongoing states
- future plans
- recorded-only facts
- derived mental-model snapshots

## Better System Design

For timeline-capable memory systems, separate the timeline anchor from the raw legacy date fields.

Recommended rollout shape:

1. keep legacy fields intact for compatibility
2. add normalized timeline metadata alongside them
3. populate new fields for new writes first
4. expose a dedicated timeline read model
5. ship the UI behind a feature flag
6. backfill historical rows in batches
7. validate with targeted checks, not only repo-global lint

## Applied Pattern

This rollout used:

- new normalized columns on `memory_units`
- temporal classification during retain and consolidation
- a dedicated `/timeline` API
- `timeline_v2` feature gating surfaced through `/version`
- an idempotent backfill command for historical data
- a dedicated timeline renderer instead of repurposing the evidence graph

## Practical Rule

If a UI needs to show "the flow of knowledge over time," do not rely on one raw timestamp.

Model at least:

- semantic occurrence
- recorded/observed time
- anchor kind
- temporal direction
- confidence when inference is involved

Then let the UI explain which anchor it is using rather than silently dropping rows.

## Validation Rule

When the repo-wide lint baseline is noisy, do not treat that as permission to skip validation.

Instead:

- run strict checks on changed files
- run typed validation for the changed subsystem
- run targeted tests for the new contract
- run the production build for UI changes
- distinguish blocking errors from pre-existing non-blocking warnings

## Expected Benefits

- timeline views stop appearing empty for recorded-only memory banks
- semantic and recorded time can coexist without corrupting recall semantics
- rollout risk stays controlled through flagging and backfills
- future temporal features can build on a stable read model instead of ad hoc UI fallbacks
