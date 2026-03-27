---
name: dependency_drift_and_reproducible_toolchains
description: Use when a previously stable development or documentation workflow starts warning or behaving differently after install, rebuild, or CI refresh. Covers identifying version drift, pinning the real dependency boundary, updating lockfiles, validating both development and production paths, and converting the incident into repeatable engineering memory.
kind: brain_protocol
---

# Dependency Drift And Reproducible Toolchains

## Purpose
This protocol handles a common modern frontend and docs failure mode:

a workflow was stable before, then a patch or transitive update changes behavior without any intentional product change.

The goal is not only to quiet the warning. The goal is to restore a reproducible toolchain that behaves the same on future installs, local machines, and CI.

## Use This Protocol When

- a warning appears after reinstall, rebuild, or branch sync even though product code did not meaningfully change
- the issue traces to a package update, especially a patch release under a caret range
- development and production behavior differ and the dependency boundary needs to be stabilized
- you want the fix to survive future `npm install` runs

## Do Not Use This Protocol When

- the warning is clearly caused by a local code change you just made
- the package update contains a required bug fix or security fix and should not be pinned back
- the issue is unrelated to dependency resolution

## Core Principles

- Treat "it was fine before" as a reproducibility problem first.
- Confirm the actual installed version, not just the declared range.
- Pin at the narrowest safe boundary that prevents drift.
- Validate both the dev path and the production build path.
- Record the learning so the repo grows operational memory, not just patches.

## Mental Model

There are four layers in dependency drift:

1. declared version ranges in package manifests
2. the concrete lockfile resolution
3. the runtime path that exposes the issue, such as dev server or build
4. the repo policy that determines whether the same drift happens again

If you only patch one layer, the warning often returns later.

## Execution Flow

### 1. Confirm The Symptom And Its Surface

Capture where the behavior appears:

- dev server only
- production build only
- both

Do not assume a dev warning is a release blocker until the production path is tested.

### 2. Identify The Package Boundary

Locate the package producing the warning and inspect:

- the declared dependency range in the relevant workspace
- the concrete installed version in the lockfile
- recent changelog notes if needed

If the manifest uses a caret range, assume silent drift is possible.

### 3. Decide The Stabilization Strategy

Preferred order:

- exact pin in the owning workspace
- root workspace override if the monorepo could resolve a different patch later
- lockfile refresh so the fix becomes concrete

This gives both local clarity and install-time enforcement.

### 4. Apply The Pin At The Real Ownership Layer

Update the package manifest that actually owns the toolchain.

In a monorepo, also consider a root override if:

- multiple workspaces can influence resolution
- hoisting may change where the package lands
- you want future installs to stay deterministic

### 5. Refresh The Lockfile Intentionally

Run a normal install from the repo root so the lockfile reflects the new contract.

Then verify that the resolved version now matches the intended exact version.

### 6. Verify Production First

Run the production build for the affected workspace.

Why:

- production is the release boundary
- some warnings are dev-only compatibility noise
- this prevents overreacting to harmless local noise

### 7. Verify The Original Runtime Path

If the complaint came from local dev startup, rerun that exact startup path too.

For example:

- the same wrapper script
- the same workspace command
- the same startup flags

This confirms the operator sees the real fix, not just a theoretical one.

### 8. Separate Remaining Known Warnings

If another warning still appears, identify whether it is:

- pre-existing and unrelated
- non-fatal and accepted
- newly introduced by the pin

Do not conflate unrelated warnings into one incident.

### 9. Persist The Learning

If the incident exposed a reusable repo lesson, capture it in the life-indexed engineering shelf.

Examples:

- exact version pinning for brittle docs plugins
- root overrides to stop workspace drift
- dev-vs-build verification as a standard release gate

## Output Contract

A successful run should leave behind:

- a pinned or otherwise stabilized dependency boundary
- an updated lockfile
- a passing production build
- a verified dev path when relevant
- a short written protocol or note explaining the pattern

## Common Failure Modes

- trusting `package.json` instead of the lockfile
- pinning only in one workspace while monorepo resolution still drifts elsewhere
- stopping after a successful build without rechecking the original failing dev command
- over-fixing a dev-only warning by making unnecessary product changes
- treating a transient install warning as the same thing as a release risk

## Recovery Mindset

Dependency drift is operational entropy.

The response is:

1. identify the boundary
2. freeze it intentionally
3. verify the important paths
4. document the learning so the same class of drift gets easier next time

## References

- Command patterns: [references/command_patterns.md](./references/command_patterns.md)
