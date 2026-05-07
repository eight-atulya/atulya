# TESTING.md

Start with [BRAIN.md](./BRAIN.md) for repo invariants and [CLAUDE.md](./CLAUDE.md)
for commands. This file is the testing source of truth for the monorepo.

## What Testing Means Here

Tests are the clearest proof of system sanity in Atulya.

- docs explain intent
- tests prove the contract
- ASD helps find impact
- green tests, not intuition, are the final confidence signal

Do not add new test machinery unless there is a clear gap. Prefer better use of
the existing suite over more framework.

## The Four Questions

Every change should answer one or more of these questions:

| Test type | Question | Typical scope |
| --- | --- | --- |
| Smoke | Is the build alive enough to continue? | Toolchain, boot path, one happy-path command |
| Retest | Did the exact bug or feature path behave correctly now? | The smallest targeted test |
| Sanity | Did the nearby area still work after the fix? | Same module, route, workflow, or client |
| Regression | Did the change break anything else that used to work? | Full affected surface, and full-system before release |

Use them in that order when practical:

1. smoke if the environment or branch feels unstable
2. retest the exact thing you changed
3. run sanity checks around the touched area
4. run broader regression only when the impact radius justifies it

## Decision Algorithm

Use this as the fast path before choosing commands:

1. If the branch or toolchain feels unstable, run one smoke check first.
2. Else, start with the smallest retest for the exact bug or feature path.
3. If the change adds or edits a public API contract, add a route or contract proof.
Then regenerate or validate downstream docs, clients, and proxy surfaces.
4. If the change materializes durable state into another bank or workspace, prove:
row fidelity, source/target isolation, non-active-state reads if supported, rollback,
delete behavior, and external artifact ownership for any pointer outside the database.
5. If the change touches concurrency, retries, scheduling, or idempotency, add a deterministic proof.
6. If the feature under test is not provider behavior itself, prefer deterministic fixtures over live provider verification.
7. After the retest is green, widen only as needed:
if the blast radius is local, run nearby sanity checks;
if the blast radius reaches shared contracts, generated clients, migrations, deployment wiring, or multiple packages, run broader regression.
8. If a production incident escaped the suite, add a named retest lane before calling the fix complete.

## Default Change Workflow

### 1. Start small

For most work, do not begin with the whole repo.

- run the smallest failing or target test first
- keep pytest sequential for LLM-backed API tests: `-p no:xdist`
- only widen scope after the narrow proof is green

### 2. Prove the local contract

Each kind of change has a minimum proof:

| Change | Minimum proof |
| --- | --- |
| Bug fix | One regression test that fails before and passes after |
| New behavior in existing module | One targeted test in the nearest existing test file, or a new focused file if none exists |
| API route or request/response field | Route or contract test, then downstream client regen/checks if public surface changed |
| Config or extension rule | One validation/load-path test plus the nearest integration path if behavior is user-visible |
| Concurrency or idempotency fix | Deterministic race, retry, or duplicate-call test |
| Storage/provider/backend adapter | Adapter test or explicit documented rationale for why an existing integration test already proves it |
| Migration | Proof that migration path is safe, or explicit note that existing migration/thread-safety tests cover it |

For storage-heavy features such as backup/restore, repo branching, cloning, snapshotting,
or any "materialize state into a new bank/workspace" behavior, minimum proof is stricter:

- one incident-shaped regression that matches the real failure mode
- one typed round-trip fidelity test for the touched tables
- one workflow isolation test that proves source and target banks stay independent
- one branch-aware read proof when users or agents can inspect non-active state without checkout
- one rollback proof when failure can happen after materialization starts but before the workflow is complete
- one external-artifact ownership proof for any restored field that points outside the database
- one delete-path proof when the feature introduces new durable artifacts or hidden workspaces

Typed round-trip means asserting the restored row values themselves, not only the API
status code. For example: `uuid`, `timestamp`, `json/jsonb`, `vector`, arrays, and any
rewritten foreign keys that must still point at the right rows after restore.

External-artifact ownership means proving what happens to things like storage keys,
archives, caches, or background-work references after clone, fork, checkout, delete,
and rollback. If ownership changes, the test should prove remap or safe sharing
explicitly.

### 3. Escalate only when the blast radius grows

Broaden from retest to sanity to regression when:

- the public API shape changed
- multiple packages depend on the changed contract
- a shared config path changed
- a migration changed data shape
- the fix touched scheduling, background work, or concurrency
- the change affects code generation, clients, or deployment wiring

## Full-Stack Feature Loop

Big features should close the loop across every contract they introduce, not only the
first backend proof.

For a feature that touches API, proxy routes, UI state, migrations, generated clients,
or deployment wiring, the default rollout loop is:

1. backend retest
2. nearby backend sanity
3. control-plane route or client proof
4. control-plane typecheck
5. repo lint flow
6. docs or workflow updates if the feature changes how future developers should validate

Minimum expectations by layer:

| Layer | Minimum proof |
| --- | --- |
| Dataplane behavior | Targeted test that proves the new branch, commit, config, or workflow contract |
| Control-plane proxy routes | Direct route/client proof, or a clear explanation of why an existing stable contract already covers it |
| UI state refresh | Proof that branch, tab, dialog, or mutation state reconnects correctly after writes; if no dedicated harness exists, document the manual smoke path and the nearest automated contract |
| Types/tooling | `cd atulya-control-plane && npm run typecheck` for TS surfaces, plus the repo lint hook before closeout |
| Public surface drift | Regenerate or explicitly audit downstream clients/docs when API shape changes |

If a layer has no harness yet, do not hand-wave it away. Prove the nearest stable
contract, call out the gap, and leave a tighter workflow behind.

For feature tests that do not exercise live provider behavior, prefer deterministic
fixtures over real provider verification. Core feature regressions should not depend on
networked LLM/provider health unless the provider contract is the thing being tested.

## Repo Surface Map

| Surface | Strong existing coverage | Confidence notes |
| --- | --- | --- |
| `atulya-api/tests/` | retain, recall/reflect paths, auth, tracing, workers, codebase import, config, concurrency, webhooks | strongest and broadest surface today |
| `atulya-cortex/tests/` | CLI, TUI, memory, conversation, setup, internet stack | good behavioral coverage |
| `atulya/tests/` and `atulya-integration-tests/tests/` | embedded package and deployment/E2E workflows | good for lifecycle and packaging sanity |
| clients and integrations | Python, TS, Go, Rust, CrewAI, LiteLLM, Pydantic AI, OpenClaw | public-surface drift is guarded, but API changes still need regen discipline |

Current audit takeaway:

- the repo already has broad tests
- the bigger gap is discoverability and scope discipline
- there is no simple maintained source-to-test matrix or coverage gate, so nobody should claim "everything is covered" without qualification

## Areas To Watch

This audit found a few areas that deserve explicit attention when touched:

- migration files are mostly protected indirectly rather than by per-revision tests
- some optional provider/backend adapters have lighter direct proof than the core API paths
- a few low-level helper modules are covered through higher-level tests rather than direct unit tests
- `bank_presets.py` and some storage/provider edges should be treated as "needs deliberate proof when changed"

That does not mean they are broken. It means they should not be edited casually
without adding or extending proof nearby.

## How ASD Should Be Used

ASD is useful here, but as an impact-analysis tool, not a test framework.

Use ASD to:

- identify touched symbols, files, and imports
- find adjacent modules that deserve sanity coverage
- trace whether a change is local, cross-module, or public-surface

Do not use ASD to:

- replace a failing or missing test
- claim system sanity without green verification
- substitute for regression coverage on public contracts

Short version: ASD tells us where to look. Tests tell us whether the system is
safe.

## Rules For Future Developers

1. Every bug fix gets a regression test as close to the bug as possible.
2. Every new public contract gets at least one direct proof test.
3. Every API shape change must be checked on downstream surfaces, not only in `atulya-api`.
4. Every concurrency fix needs deterministic proof, not "seems fine locally".
5. Prefer behavior and contract tests over implementation-shaped tests.
6. Do not add broad E2E coverage when a smaller stable contract test proves the same thing.
7. If a change ships without a new or updated test, the summary must explain why.
8. When tests and docs disagree, treat the mismatch as unfinished work.
9. Large features must update the validation workflow if they expose a repeatable new failure mode or rollout pattern.
10. Every production incident that escapes the suite should become a named retest lane before the fix is considered complete.
11. Snapshot/restore/versioning features must prove data fidelity at the row/type level, not just successful orchestration.
12. Non-provider feature tests should use deterministic fixtures so signal is not hidden by unrelated external verification failures.
13. If a restored row contains a pointer to external state such as `*_storage_key`, the suite must prove who owns that artifact after restore and after delete.
14. Delete and rollback are part of the contract for materialization features; do not call clone/fork/branch features production-safe until those paths are tested too.

## Practical Commands

Use [CLAUDE.md](./CLAUDE.md) for exact commands and
[skills/atulya-system-testing/SKILL.md](./skills/atulya-system-testing/SKILL.md)
for the full monorepo regression workflow.
