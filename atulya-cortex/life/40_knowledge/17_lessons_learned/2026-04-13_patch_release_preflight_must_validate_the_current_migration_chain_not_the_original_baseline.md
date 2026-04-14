# Patch Release Preflight Must Validate The Current Migration Chain, Not The Original Baseline

## What happened

The `0.8.1` release flow was blocked by `scripts/release-preflight-v0800.sh` even though `main` was healthy.

The script still assumed the `v0.8.x` line should contain exactly one Alembic migration file and that the expected schema revision was the original `0.8.0` baseline. By `2026-04-13`, the repo legitimately contained additional `v0.8.x` migrations for async operations, Dream tables, timeline metadata, and Codebases review tables.

## Why it happened

The release preflight encoded the *starting point* of the `0.8.x` migration line as if it were the permanent shape of the branch.

That caused two forms of drift:

1. it rejected a valid linear migration chain after the baseline
2. it asserted an outdated fresh-database table list that no longer matched current `main`

## The durable rule

Patch-release preflight scripts for a live version line must validate the **current head chain** and the **current schema outcome**, not the original baseline snapshot alone.

For `v0.8.x`, the correct checks are:

- the baseline root migration still exists
- the migration chain is linear and has exactly one head
- fresh public and tenant migrations land at the current head revision
- the resulting schema matches the tables and matviews expected by current `main`

## What to do next time

Before cutting a patch release:

1. run the line-specific preflight against current `main`
2. if it fails on migration shape, inspect whether the script is stale before assuming the repo is broken
3. update the preflight script first, then rerun the release validation

## Why this matters

Release automation should protect the real production contract.

If the preflight remains frozen at the original baseline, patch releases become artificially blocked and operators lose trust in the release pipeline.
