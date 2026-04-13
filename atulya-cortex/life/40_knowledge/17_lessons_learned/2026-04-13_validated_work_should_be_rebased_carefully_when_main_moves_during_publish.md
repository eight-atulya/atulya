# Validated Work Should Be Rebased Carefully When Main Moves During Publish

Date: 2026-04-13
Repo: atulya
Area: git, publish hygiene, rebase conflicts, validation, main branch

## Trigger

An ASD-first codebase rollout was fully implemented and validated locally, but `origin/main` moved before publish.

The local branch was:

- ahead by one validated commit
- behind by one new upstream commit
- touching the same codebase surfaces as the upstream change

That meant a straight push would either fail or tempt a risky overwrite of `main`.

## Root Cause

The real problem was not Git conflict itself. The real problem was timing plus overlap:

- the local rollout touched API, control-plane, docs, and generated OpenAPI
- upstream landed another codebase change in the same files
- validation had already passed on the pre-rebase tree, but that did not prove the merged result

When `main` moves during publish, the validated state is no longer the final publish candidate.

## Better Publish Pattern

When local work is ready but `origin/main` has advanced:

1. confirm the local scope is intentional
2. inspect the upstream delta before integrating it
3. create the local commit first so the work is preserved as one unit
4. rebase onto the newer `origin/main`
5. resolve only the actual semantic overlaps
6. rerun the important validation on the merged result
7. push only after the rebased tree is green

This keeps history clean without treating pre-rebase validation as sufficient proof.

## Applied Pattern

The successful publish flow used:

- `git fetch origin` before push
- inspection of `origin/main` to understand the new codebase-related commit
- a local commit before rebase so the rollout stayed intact as one change
- conflict resolution that preserved both feature lines:
  - upstream repo URL import and pending cancellation improvements
  - local ASD chunk review queue and selective hydration changes
- non-interactive rebase continuation with `GIT_EDITOR=true git rebase --continue`
- rerunning lint, targeted tests, and generated docs/OpenAPI after conflict resolution

## Practical Rule

If the branch is both `ahead` and `behind` right before publish, do not treat that as a minor nuisance.

Use this rule:

- if the upstream change overlaps your files, rebase and revalidate
- if the rebase introduces conflicts in generated surfaces, regenerate them instead of hand-editing more than necessary
- if Git requests an editor during a non-interactive rebase, continue explicitly rather than dropping into an interactive shell

## Validation Rule

After resolving a rebase on moving `main`, rerun the checks that prove the release-facing result, not just generic Git cleanliness.

For this repo shape that means at least:

- `./scripts/hooks/lint.sh`
- targeted tests for the changed subsystem
- `./scripts/generate-openapi.sh` when API contracts changed

Do not publish a rebased merge result based only on the fact that the earlier, pre-rebase tree was green.

## Failure Modes To Avoid

- pushing directly over a newer `main`
- resolving only text conflicts without checking semantic compatibility
- assuming generated files are still correct after conflict resolution
- letting `git rebase --continue` stall because `EDITOR` is unset in a dumb terminal
- skipping a second validation pass because the pre-rebase commit had already passed

## Expected Benefits

- main stays linear and trustworthy
- upstream changes are preserved instead of accidentally overwritten
- final validation matches the actual pushed tree
- future agents can handle moving-main publish windows calmly instead of treating them as emergencies

## Cortex Links

- Related protocol: [git_history_rewrite_and_branch_realignment](../../03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/git_history_rewrite_and_branch_realignment/BRAIN.md)
- Related publish protocol: [full_stack_feature_rollout_and_batch_publish](../../03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/full_stack_feature_rollout_and_batch_publish/BRAIN.md)
- Root brain contract: [BRAIN.md](../../../../../BRAIN.md)
