# Route To Memory Actions Should Queue Real Async Hydration And Approved History Should Lazy Load

Date: 2026-04-13
Repo: atulya
Area: codebases, ASD review queue, control-plane UX, async operations

## Trigger

The Codebases workbench exposed `Memory` actions in the review and research queues, but users observed that clicking them did not actually place any memory-intake work into the async operations queue.

At the same time, operators needed a meaningful way to inspect what had already been approved into memory without forcing the workbench to load the whole repo eagerly.

## Root Cause

The UI and backend semantics had drifted apart:

- the UI labeled the action as if it would send code into memory
- the backend route endpoint only updated `codebase_review_routes`
- no async `codebase_approve` operation was submitted from that action path

So the system changed review metadata but did not perform the heavier memory hydration step the user expected.

The approved-memory visibility gap was a separate UX issue, but the right fix followed the same design rule: use existing precise snapshot-aware APIs instead of inventing a heavier summary fetch.

## Correct Pattern

When a codebase UI action implies a background workflow, the API contract should surface that workflow explicitly.

For this codebase review flow:

1. bulk-route chunks to `memory`
2. optionally queue async hydration in the same request path
3. return `operation_id` and queue state to the UI
4. let the UI bind its status card and polling to that operation

Do not make the operator guess whether a route update is only metadata or whether it triggered real memory work.

## Applied Fix

The durable production shape was:

- extend the route request with `queue_memory_import`
- have the backend submit `codebase_approve` when routing to memory from the interactive UI
- dedupe approval jobs by `codebase + snapshot` so repeated clicks do not spam pending operations
- return `operation_id` and `queued_for_memory` in the route response
- update the control plane to start polling the queued approval immediately

For approved history:

- add an `Approved Memory` workbench tab
- lazy-load approved chunks only when the tab is opened
- fetch them using the existing chunk listing API with `snapshot_id=approved_snapshot_id` and `route_target=memory`
- keep the first screen lightweight and use detail dialogs for deeper inspection

## Practical Rule

For operator-facing async systems:

- if the button language implies background execution, return an operation handle
- if the user needs historical visibility, prefer lazy loading over eager whole-page fetches
- if the API already supports snapshot-scoped reads, reuse that path before adding a new endpoint

## Failure Modes To Avoid

- updating only route metadata while presenting the action as memory ingestion
- forcing users to click a second hidden approval step when the first action claims the work is already being sent
- queuing duplicate approval operations for the same snapshot
- loading full approved-history state on every workbench render for large repositories
- adding a new backend endpoint when the existing chunk API already supports the required snapshot filter

## Validation Rule

For this codebase surface, validate all three layers together:

- `./scripts/hooks/lint.sh`
- targeted codebase tests proving the route action returns an operation id and completes hydration
- `./scripts/generate-openapi.sh` when the route contract changes

## Expected Benefits

- operators can trust that `Memory` means real async hydration work was queued
- approval status is visible immediately through the standard operation card
- duplicate clicks are safer
- approved memory state is inspectable without slowing the default codebase page
- the review queue and approved history remain repo-scale friendly

## Cortex Links

- Related publish lesson: [validated_work_should_be_rebased_carefully_when_main_moves_during_publish](./2026-04-13_validated_work_should_be_rebased_carefully_when_main_moves_during_publish.md)
- Related publish protocol: [full_stack_feature_rollout_and_batch_publish](../../03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/full_stack_feature_rollout_and_batch_publish/BRAIN.md)
- Root brain contract: [BRAIN.md](../../../../../BRAIN.md)
