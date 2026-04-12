# Stale Next Build Artifacts Can Mask The Real Control Plane Failure

Date: 2026-04-12
Repo: atulya
Area: control plane, Next.js, TypeScript validation, publish hygiene

## Trigger

The control-plane production build failed while validating `brain-lab` routes that no longer existed in the source tree. That made the new brain-intelligence workspace work look suspicious even though the visible error did not point at any live file we were editing.

## Root Cause

The real issue was stale generated Next.js type output being treated as active TypeScript input:

- the control plane had several old `.next-*` directories
- generated validator files inside those folders still referenced deleted `brain-lab` pages and route handlers
- `tsconfig.json` included both `.next` and wildcard historical `.next-*` type paths, so TypeScript kept compiling stale route metadata

Once those stale artifacts were removed, the actual source-level failure surfaced: a new cockpit recommendation used `tone: "neutral"` while the `Recommendation` type only allowed `"good"`, `"warn"`, and `"critical"`.

## Applied Fix

The reliable recovery path was:

1. remove stale build artifacts with `rm -rf .next .next-* standalone/.next`
2. rerun the control-plane production build
3. fix the real source error that appeared after cleanup

For this incident, the code fix was a small type update in `brain-cockpit.tsx` so the `Recommendation` union matched the values already rendered by the UI.

## Practical Rule

When a Next.js control-plane build fails on routes or pages that do not exist anymore:

- treat generated `.next` output as disposable cache, not source of truth
- clean stale `.next` and `.next-*` directories before trusting the error
- only after cleanup decide whether the failure is in live code or in stale build state

If the repo intentionally includes Next-generated type paths, prefer only the current `.next` output and avoid historical wildcard folders that can resurrect deleted routes.

## Validation Rule

For this class of incident:

- run the cleanup step before drawing conclusions from TypeScript route-validator failures
- rerun `npm run build` in `atulya-control-plane`
- if a new source error appears after cleanup, fix that error and rerun the build again

The publish decision should be based on the post-cleanup build result, not the first stale-artifact failure.

## Expected Benefits

- deleted routes do not keep failing future builds through stale generated metadata
- source-level regressions surface faster
- publish confidence improves because build output reflects the live tree instead of old cache state
- control-plane debugging time shifts from cache-chasing to real fix validation
