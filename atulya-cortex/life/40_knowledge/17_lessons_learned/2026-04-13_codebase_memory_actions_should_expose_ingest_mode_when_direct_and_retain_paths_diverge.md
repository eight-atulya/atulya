# Codebase Memory Actions Should Expose Ingest Mode When Direct And Retain Paths Diverge

Date: 2026-04-13
Repo: atulya
Area: codebases, memory ingestion, control-plane UX, ASD review

## Trigger

The Codebases workbench allowed reviewed ASD chunks to be sent to memory, but the actual hydration path used a direct deterministic document write rather than the richer retain pipeline.

That created a product-level ambiguity:

- operators believed "send to memory" meant full memory ingestion
- the system actually chose the faster deterministic path silently
- richer retain-time semantic linking was not being used unless someone knew the backend implementation details

## Root Cause

The issue was not a broken queue or a missing operation.

The deeper problem was a hidden semantic choice:

- `ASD Direct` and `Retain Pipeline` are both valid
- they optimize for different outcomes
- the operator was not told which one would run

When two memory-ingest paths have meaningfully different behavior, silently picking one creates a trust gap.

## Better Pattern

If the system has both:

- a deterministic, low-cost path
- a richer, more semantically expressive ingest path

then the operator-facing workflow should expose that as an explicit choice before queueing the work.

For codebase review, the right shape is:

1. show the reviewed chunk context first
2. explain the two ingest modes in human terms
3. queue the chosen mode asynchronously
4. return the ingest mode in the operation result so the UI and logs stay honest

## Applied Rule

The durable implementation rule is:

- default to `retain` in the modal when the user is making a deliberate memory decision
- keep `direct` available for repo-scale speed and deterministic syncing
- make the backend contract carry `memory_ingest_mode` end-to-end
- make dedupe keys include ingest mode when queue semantics differ

This preserves both performance and operator control.

## Failure Modes To Avoid

- presenting one button label for two materially different ingest behaviors
- forcing all reviewed code through the heavy retain path when the operator really wants exact deterministic sync
- hardwiring only the fast path and pretending it gives full retain semantics
- returning an operation id without recording which ingest path was actually queued

## Validation Rule

When this kind of ingest-mode choice is introduced:

- lint the control-plane and API changes
- run targeted tests that prove the richer path actually works
- regenerate OpenAPI when the public contract changes

## Expected Benefits

- operators understand the tradeoff between speed and richer semantic linking
- memory ingestion becomes more trustworthy because it is explicit
- ASD-reviewed context can enrich retain without replacing retain
- the deterministic fast path remains available for large repos and low-latency workflows

## Cortex Links

- Related lesson: [route_to_memory_actions_should_queue_real_async_hydration_and_approved_history_should_lazy_load](./2026-04-13_route_to_memory_actions_should_queue_real_async_hydration_and_approved_history_should_lazy_load.md)
- Related publish lesson: [validated_work_should_be_rebased_carefully_when_main_moves_during_publish](./2026-04-13_validated_work_should_be_rebased_carefully_when_main_moves_during_publish.md)
- Related protocol: [full_stack_feature_rollout_and_batch_publish](../../03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/full_stack_feature_rollout_and_batch_publish/BRAIN.md)
