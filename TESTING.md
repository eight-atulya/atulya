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

### 3. Escalate only when the blast radius grows

Broaden from retest to sanity to regression when:

- the public API shape changed
- multiple packages depend on the changed contract
- a shared config path changed
- a migration changed data shape
- the fix touched scheduling, background work, or concurrency
- the change affects code generation, clients, or deployment wiring

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

## Practical Commands

Use [CLAUDE.md](./CLAUDE.md) for exact commands and
[skills/atulya-system-testing/SKILL.md](./skills/atulya-system-testing/SKILL.md)
for the full monorepo regression workflow.
