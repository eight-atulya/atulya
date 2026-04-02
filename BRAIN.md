---
name: atulya_repo_brain
kind: repo_brain
schema_version: 1
repo: atulya
source_of_truth: atulya_memory_plus_repo_contract
update_mode: append_then_refresh
read_window_strategy: bootstrap_plus_recency
refresh_policy:
  stable_sections_preserved: true
  generated_sections_only: true
  full_file_rewrite_allowed: false
generated_sections:
  - active_context
  - durable_mental_models
  - recent_learnings_and_protocol_links
  - open_loops_and_next_actions
  - refresh_metadata
---

# Atulya Repo Brain

## Identity And Operating Contract

This is the primary agent-facing brain contract for the `atulya` repo.

Atulya is a memory-native agent system built around:

- `retain` for storing facts, entities, relationships, and evidence
- `recall` for retrieving relevant memory through semantic, keyword, graph, and temporal signals
- `reflect` for producing reasoning shaped by memory, mission, directives, and mental models
- Brain and Dream as the direction for higher-order learning, influence tracking, synthesis, and integrity-aware memory workflows

Instruction hierarchy for this repo:

1. `BRAIN.md` is the primary repo brain layer
2. `AGENTS.md` points agents into the brain-first workflow
3. `CLAUDE.md` holds concrete dev commands and local coding conventions

Operating rules:

- treat stable sections in this file as the preserved contract
- only refresh sections explicitly marked as generated
- do not free-form rewrite the entire file during a brain refresh
- retain new evidence in Atulya before refreshing generated sections
- generated sections are summaries of memory and repo state, not the only source of truth

## System Architecture

Atulya is a monorepo with a memory-system core and multiple operator surfaces:

- `atulya-api/`: FastAPI dataplane for retain, recall, reflect, mental models, directives, Brain, and Dream operations
- `atulya-control-plane/`: Next.js admin and operator UI
- `atulya/`: embedded Python package bundle
- `atulya-cli/`: Rust CLI
- `atulya-clients/`: generated SDKs
- `atulya-docs/`: product and developer documentation
- `atulya-cortex/`: repo-native procedural memory, brain protocols, and learned workflows
- `atulya-dev/`: benchmarks and development tooling

Core flow:

1. `retain` stores raw memories and extracts structured facts, entities, and links
2. consolidation upgrades raw memory into observations and related knowledge
3. `recall` retrieves from multiple search paths and reranks evidence
4. `reflect` reasons over memories, observations, directives, and mental models
5. Brain and Dream extend the system toward influence analytics, synthesis, integrity maintenance, and portable learning

Knowledge layers to keep distinct:

- facts record specific evidence
- observations capture synthesized patterns
- mental models are curated reusable summaries for common queries
- directives constrain allowed reasoning behavior
- Brain tracks activity, influence, and integrity-oriented patterns
- Dream creates higher-level background takeaways

## Repo Invariants

- Each request operates on a single memory bank. No cross-bank leakage is acceptable.
- `reflect` is the reasoning surface. `recall` is the retrieval surface. Do not blur their responsibilities.
- Mental models summarize and accelerate reasoning, but they do not replace underlying evidence.
- Control-plane proxy routes and generated client types must stay in sync with dataplane API changes.
- Python and TypeScript changes should validate through the repo lint flow: `./scripts/hooks/lint.sh`.
- Architecture-facing changes should preserve public contracts unless the change explicitly updates downstream surfaces and docs.
- Cortex lessons and protocols should capture durable workflow learning instead of leaving it buried in chat history or commit messages.

## Brain Read Contract

How to consume this file efficiently:

- always read the first block first for identity, architecture, and invariant rules
- always read the final generated block for active state, open loops, and next actions
- read the middle sections only when the task needs deeper repo context
- treat generated sections as compact summaries backed by Atulya memory, repo files, and Cortex artifacts
- when updating the brain, retain the evidence first, then refresh only the generated blocks below

## Generated: Active Context
<!-- BRAIN:BEGIN GENERATED:active_context -->

- The repo is operating with `BRAIN.md` as the primary agent brain layer, while `CLAUDE.md` remains the detailed mechanics reference.
- Recent active work included graph-intelligence contract protection and control-plane mental-model UI fixes.
- Current priority is making repo memory more explicit and token-efficient by moving high-signal context into a stable-plus-generated root brain contract.
- Risk theme: do not let living brain content become a noisy changelog; generated sections must stay compact and evidence-backed.
- Branch reality: generated repo-brain content should describe durable repo state, not temporary branch-local drift, unless the branch state materially affects operators.

<!-- BRAIN:END GENERATED:active_context -->

## Generated: Durable Mental Models
<!-- BRAIN:BEGIN GENERATED:durable_mental_models -->

- Atulya is not a generic prompt-memory addon. Its core value is structured, evidence-backed memory with retrieval and reasoning separated cleanly.
- Repo-specific procedural learning belongs in `atulya-cortex`, usually as lessons learned first and brain protocols when the workflow becomes reusable.
- Semantic or heuristic upgrades should preserve the subsystem contract first, then add smarter behavior behind targeted validation.
- Publish hygiene is part of system integrity. Scope, validation, and reusable learning capture matter alongside the code diff.
- Agent context should be front-loaded with durable identity and tailed with compact recency. Middle detail is optional and should stay skimmable.

<!-- BRAIN:END GENERATED:durable_mental_models -->

## Generated: Recent Learnings And Protocol Links
<!-- BRAIN:BEGIN GENERATED:recent_learnings_and_protocol_links -->

Recent high-signal learnings:

- [Root Repo Brain Should Separate Stable Contract From Generated State](./atulya-cortex/life/40_knowledge/17_lessons_learned/2026-04-02_root_repo_brain_should_separate_stable_contract_from_generated_state.md)
  A root living brain should preserve stable contract sections while refreshing only marked generated state from Atulya memory.
- [Graph Intelligence Semantic Rewrites Need Contract Tests And A Tiny Real-Retain Corpus](./atulya-cortex/life/40_knowledge/17_lessons_learned/2026-04-02_graph_intelligence_semantic_rewrites_need_contract_tests_and_real_retain_corpus.md)
  Semantic read-model improvements should be proven through both contract tests and a tiny retain-backed realism lane before they become the new baseline.
- [Mental Model UI Needs Wrap-Safe Detail Panels And Multiline Query Inputs](./atulya-cortex/life/40_knowledge/17_lessons_learned/2026-04-02_mental_model_ui_needs_wrap_safe_detail_panels_and_multiline_query_inputs.md)
  Long prompt-like text needs wrap-safe detail views and textarea editing surfaces rather than assuming short single-line content.
- [Dual Time Timeline Rollouts Need Feature Flags, Backfills, And Targeted Validation](./atulya-cortex/life/40_knowledge/17_lessons_learned/2026-03-31_dual_time_timeline_rollouts_need_feature_flags_backfills_and_targeted_validation.md)
  Timeline-facing rollouts should separate model changes, backfill shape, and operator validation rather than shipping as one lump.

Relevant reusable protocols:

- [semantic_read_model_salvage_and_retain_backed_validation](./atulya-cortex/life/03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/semantic_read_model_salvage_and_retain_backed_validation/BRAIN.md)
- [dependency_drift_and_reproducible_toolchains](./atulya-cortex/life/03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/dependency_drift_and_reproducible_toolchains/BRAIN.md)
- [git_history_rewrite_and_branch_realignment](./atulya-cortex/life/03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/git_history_rewrite_and_branch_realignment/BRAIN.md)
- [full_stack_feature_rollout_and_batch_publish](./atulya-cortex/life/03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/full_stack_feature_rollout_and_batch_publish/BRAIN.md)

<!-- BRAIN:END GENERATED:recent_learnings_and_protocol_links -->

## Generated: Open Loops And Next Actions
<!-- BRAIN:BEGIN GENERATED:open_loops_and_next_actions -->

- Open loop: trace and fix the path that allows local-model control tokens such as `<|channel|>` to leak into saved mental model content.
- Open loop: define or implement the future section-refresh tooling that rewrites only generated blocks in this file.
- Next action: when new high-signal incidents land, retain them with `repo:atulya`, `brain:root`, and area tags before refreshing this brain.
- Next action: keep stale resolved items out of this tail section so the last tokens remain a high-signal bootstrap surface.

Staleness rule:

- remove or compact items here once they are resolved, superseded, or no longer operator-relevant

<!-- BRAIN:END GENERATED:open_loops_and_next_actions -->

## Generated: Refresh Metadata
<!-- BRAIN:BEGIN GENERATED:refresh_metadata -->

- Last refreshed: 2026-04-02
- Refresh mode: manual v1 seed following the append-then-refresh contract
- Evidence sources:
  - root repo contract in this file
  - `CLAUDE.md`
  - `AGENTS.md`
  - Cortex lessons learned in `atulya-cortex/life/40_knowledge/17_lessons_learned/`
  - Cortex brain protocols in `atulya-cortex/life/03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/`
- Recall scope:
  - `repo:atulya`
  - `brain:root`
  - recent lessons
  - active engineering protocols
- Confidence note: high for repo identity, architecture, and invariants; medium for active-context recency until automated refresh tooling exists
- Refresh horizon: prioritize recent lessons and active protocol surfaces, then compact older context into durable mental models

<!-- BRAIN:END GENERATED:refresh_metadata -->
