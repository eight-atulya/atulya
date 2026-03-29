---
name: full_stack_feature_rollout_and_batch_publish
description: Use when one feature spans backend behavior, UI, docs, and operational learning, and the team needs to decide whether to publish as one push or split the work into meaningful batches. Covers scope mapping, batch boundaries, validation, and learning capture before push.
kind: brain_protocol
---

# Full Stack Feature Rollout And Batch Publish

## Purpose
This protocol helps ship large cross-layer features without turning Git history into one hard-to-review blob.

The goal is to keep the publish flow meaningful:

- each commit should represent a real deliverable
- validation should match the layer that changed
- docs and learning should land with the feature, not as an afterthought

## Use This Protocol When

- one feature touches backend, frontend, and docs together
- the worktree is large enough that a single commit would hide useful structure
- the team wants better rollback, review, or cherry-pick options
- the task revealed reusable operational learning that should stay in Cortex

## Do Not Use This Protocol When

- the work is truly one small atomic fix
- splitting the changes would leave intermediate commits broken
- the feature depends on one inseparable migration or schema boundary

## Core Principles

- Split by deliverable, not by file count.
- Prefer a small number of meaningful commits over one giant commit or many tiny ones.
- Validate the important path for each layer before staging it.
- Keep docs and operational learning close to the feature.
- If a batch cannot stand on its own, do not force the split.

## Mental Model

Think in layers:

1. **backend capability** — the new behavior and API surfaces
2. **product surface** — the control plane, UX, and runtime integration
3. **explanation layer** — docs, screenshots, changelog, onboarding
4. **repo memory** — the reusable workflow or protocol learned from doing the work

Good batching keeps these layers legible in Git history.

## Execution Flow

### 1. Reconstruct The Actual Feature

Write down what the feature really is in user terms.

For example:

- new graph intelligence read model
- new graph workbench experience
- new docs for operators and developers

Do not batch by directory until the product shape is clear.

### 2. Map The Worktree By Deliverable

Group changed files into natural publish units:

- backend engine and API
- frontend product integration
- docs and assets
- learning artifacts

If a file is shared across layers, decide which deliverable it serves most directly.

### 3. Check Whether The Batches Stand Alone

For each proposed batch, ask:

- does this commit represent a coherent improvement?
- would a future reader understand why it exists?
- could this batch be reverted or cherry-picked without confusion?

If yes, keep the split.
If no, merge that batch with its nearest dependency.

### 4. Validate Each Layer On Its Own Boundary

Examples:

- backend: targeted tests, lint, API behavior
- frontend: typecheck, build, targeted lint
- docs: docs build and link/image verification

Do not claim production confidence from only one layer's checks.

### 5. Stage Explicit Paths Only

Use path-based staging when the tree is mixed.

That keeps accidental unrelated edits out of the publish flow and makes the batch boundaries real.

### 6. Capture The Reusable Learning

If the work exposed a repeatable pattern, add or update a Cortex protocol before push.

Typical examples:

- how to batch a large full-stack feature
- how to validate a graph-heavy UI rollout
- how to handle docs assets and screenshots cleanly

### 7. Push The Branch After The Story Is Clear

Push once the commit sequence tells the story well.

A good branch history for a large feature often looks like:

1. backend capability
2. frontend product surface
3. docs and release narrative
4. repo-native learning

## Output Contract

A successful run should leave behind:

- a small set of meaningful commits
- targeted validations for each layer
- docs that explain the feature in plain language
- a reusable Cortex protocol when the rollout exposed a new pattern

## Decision Guardrails

- Do not split commits so finely that none of them mean anything.
- Do not lump docs into code commits when the docs tell a separate product story.
- Do not push one giant commit just because the worktree is large.
- Prefer batch boundaries that make future rollback and review easier.

## Common Failure Modes

- batching by file count instead of by deliverable
- forgetting docs because the UI already "works"
- validating only the frontend for a backend-backed feature
- capturing the learning in chat but not in the repo
- creating so many commits that the history becomes noise

## References

- `git-push-learning-loop` skill for the publish reasoning chain
