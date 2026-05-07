# Memory Repo Materialization Features Need Row-Level Restore Proofs, Rollback Guards, And Downstream Contract Checks

Date: 2026-05-07
Repo: atulya
Area: memory repos, snapshot restore, bank forking, control plane, generated clients, test strategy

## Trigger

The memory-repo rollout added branch workspaces, checkout, commit, reset, branch-aware reads, and finally fork-to-new-bank support.

The first implementation looked functionally complete, but real usage exposed several failures that the original test shape did not catch:

- branch creation collided on globally keyed rows such as `chunks.chunk_id`
- restored `pgvector` values were double-encoded and failed on insert
- repo UI summary cards showed `No commits` even while the branch log showed real commits
- a forked bank could have been left partially materialized if post-restore steps failed

## Root Cause

The real issue was not one endpoint bug. It was a repeated systems pattern around materialized state:

- snapshot restore initially proved orchestration more than restored row fidelity
- workspace banks reused source identities unless restore-time remapping covered every globally keyed table and foreign-key edge
- typed columns such as `vector` needed explicit round-trip handling instead of generic serialization assumptions
- backend, control plane, OpenAPI, generated SDKs, MCP tools, and UI cards all depended on the same repo contract, but not every layer was being proven directly
- failure handling was strong inside the main transaction, but follow-up work after materialization still needed cleanup guarantees

## Better Design Rule

For any feature that materializes durable memory state into another bank or workspace:

1. treat restore as a typed data migration, not just a copy workflow
2. remap every globally keyed identifier and all dependent references as one explicit restore context
3. prove restored row values directly for tricky types such as `uuid`, `json/jsonb`, arrays, timestamps, and `vector`
4. normalize hidden workspace identity back to logical root-bank identity anywhere diff, status, or UI summary reads compare snapshots
5. make post-restore steps failure-safe by rolling back the target bank if file persistence, repo enablement, or other follow-up work fails
6. when the public contract changes, regenerate and validate every downstream surface before calling the feature production-ready

## Practical Pattern

The publish-safe shape that worked here was:

- restore-time ID remap maps for globally keyed tables and foreign keys
- explicit vector round-trip handling instead of generic JSON encoding
- repo summary reads joined to active-branch HEAD metadata instead of assuming a raw repo row contains enough UI data
- fork cleanup logic that deletes the newly created bank if later steps fail
- direct bank, HTTP, MCP, control-plane, and generated-client proofs for the same repo contract

## Publish-Safe Validation Rule

For memory repo, snapshot, clone, branch workspace, or fork-bank changes:

- add one incident-shaped regression for each escaped production failure mode
- add one row-level fidelity proof for the touched restored tables
- add one isolation proof showing source and target state do not leak into each other
- add one non-active-state read proof if branches or snapshots can be inspected without checkout
- add one rollback proof for failures that happen after materialization begins
- regenerate OpenAPI and client SDKs when the route or request shape changes
- finish with downstream checks such as control-plane typecheck, CLI/client validation, and the repo lint hook

## Failure Modes To Avoid

- assuming `bank_id` rewrite alone is enough for cloned or branched state
- treating typed column serialization as generic JSON
- trusting one UI panel when another panel is driven by a different summary source
- declaring a feature production-ready before the generated SDKs and proxy routes are refreshed
- leaving a newly created bank behind when follow-up work fails after restore

## Expected Benefits

- memory repo features behave more like durable version-control primitives and less like ad hoc copy flows
- escaped restore bugs become much harder because the suite now proves row fidelity, isolation, and rollback explicitly
- control plane and agent surfaces stay aligned with the dataplane contract
- future repo-versioning work has a clearer production checklist instead of rediscovering the same failure class

## Cortex Links

- Related root contract: [BRAIN.md](../../../../../BRAIN.md)
- Related rollout mechanics: [CLAUDE.md](../../../../../CLAUDE.md)
- Related testing source of truth: [TESTING.md](../../../../../TESTING.md)
- Related publish protocol: [full_stack_feature_rollout_and_batch_publish](../../03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/full_stack_feature_rollout_and_batch_publish/BRAIN.md)
