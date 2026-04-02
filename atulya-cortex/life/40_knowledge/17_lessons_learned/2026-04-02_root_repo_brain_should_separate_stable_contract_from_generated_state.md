# Root Repo Brain Should Separate Stable Contract From Generated State

Date: 2026-04-02
Repo: atulya
Area: repo operations, agent context, Cortex memory, living documentation

## Trigger

The repo needed a better top-level operating surface than a static external-skills style file. The goal was to make agent context more token-efficient and meaningfully grounded in Atulya's own memory model, while still keeping the repo's instruction contract readable and stable.

## Root Cause

The problem was not simply "missing docs." The repo had useful guidance, but it was split across lightweight entry files and a large command-heavy reference. That shape made it harder to express three things together:

- durable repo identity and architecture
- living high-signal context such as recent learnings and open loops
- a safe update mechanism that does not let generated content rewrite the whole contract

Without that separation, a "living brain" would either stay too static to help, or become too free-form to trust.

## Applied Pattern

The safer pattern is a root `BRAIN.md` with two layers:

1. a stable contract layer that defines identity, architecture, invariants, and read/update rules
2. generated sections that can be refreshed from Atulya memory without rewriting the whole file

The key control is explicit refresh markers:

- `<!-- BRAIN:BEGIN GENERATED:<section> -->`
- `<!-- BRAIN:END GENERATED:<section> -->`

This makes the file compatible with append-then-refresh workflows:

- retain evidence into Atulya first
- recall only the evidence needed for one section
- reflect a compact section summary
- refresh only the marked generated block

## Practical Rule

For repo-level living brain files:

- put bootstrap-critical identity and invariants at the top
- put recency-critical active state and open loops at the bottom
- keep the middle skimmable and architecture-oriented
- never let the updater free-form rewrite stable contract sections
- treat generated content as summary memory, not as the only source of truth

## When To Use This Pattern

Use a root repo brain contract when:

- the repo has durable operating rules plus evolving context
- the team wants Atulya-native memory workflows instead of generic prompt files
- token efficiency matters for repeated agent startup
- lessons learned and protocols should be discoverable from the repo entrypoint

Do not use this pattern if the repo only needs a static conventions file and has no meaningful living operational context.

## Expected Benefits

- faster agent bootstrap from the first tokens
- better recency handoff from the last tokens
- cleaner separation between stable instructions and living repo state
- safer future automation for brain refreshes
- tighter alignment between repo operations and Atulya's retain/recall/reflect model
