---
name: pypi_release_fallback_and_tag_realignment
description: Use when a tag-triggered Python release is blocked by PyPI trusted-publisher setup, token fallback must be enabled temporarily, and the release tag may need to be moved so the rerun uses the corrected workflow snapshot.
kind: brain_protocol
---

# PyPI Release Fallback And Tag Realignment

## Purpose
This protocol restores a blocked Python release without losing the long-term Trusted Publishing direction.

It exists for incidents where:

- the release workflow was written for PyPI Trusted Publishing
- the real package or publisher registration is not ready yet
- the release tag has already been created
- the workflow file itself must change before the release can succeed

## Use This Protocol When

- a tag-triggered GitHub release fails during PyPI publish
- local package metadata looks valid, but publishing still fails
- a temporary PyPI API token fallback is acceptable
- the release tag must be reattached to a newer commit so the rerun sees the workflow fix

## Do Not Use This Protocol When

- the failure is clearly caused by malformed package metadata or a bad build artifact
- the package version itself must change
- the release tag must remain immutable for policy reasons
- the workflow already supports the needed auth mode and only secrets are missing

## Core Principles

- Verify the build artifact before blaming package metadata.
- Treat auth/orchestration failures differently from packaging failures.
- Keep Trusted Publishing as the default path.
- Use token fallback as a temporary release-unblock mechanism, not as the long-term end state.
- If the workflow file changes after a release tag exists, move the tag intentionally so the rerun uses the corrected workflow snapshot.

## Mental Model

There are four layers in this incident type:

1. package metadata and build artifacts
2. publish authentication mode
3. the workflow definition stored at the tagged commit
4. the remote tag that triggers the release

If you only fix one layer, the release can keep failing in exactly the same way.

## Execution Flow

### 1. Verify The Artifact First

Build the package locally and run `twine check`.

If the wheel and sdist pass, treat the incident as workflow/auth state first, not packaging first.

### 2. Confirm The Auth Assumption

Check whether the workflow is relying on:

- `id-token: write` plus Trusted Publishing
- or token-based upload using a secret

If Trusted Publishing is configured in the workflow but PyPI registration is incomplete, that mismatch is the real blocker.

### 3. Add Dual-Mode Publishing

Patch the workflow so:

- Trusted Publishing remains the default
- token fallback is used only when the PyPI token secret is present

Do not permanently replace OIDC with token uploads unless the repo has chosen that intentionally.

### 4. Rebuild Confidence In The Workflow

Validate the workflow file itself before publishing:

- YAML parses cleanly
- publish order is still correct
- fallback conditions are mutually exclusive

### 5. Commit The Workflow Fix

Commit only the release-workflow change and any explicit procedural memory that belongs with it.

Do not mix unrelated product or docs edits into the release-recovery commit.

### 6. Move The Release Tag Intentionally

If the release is tag-triggered and the old tag points to a commit without the workflow fix:

- inspect the current tag target
- delete and recreate the local tag on the new commit
- use an annotated tag message that explains the release intent

This is not cosmetic. The workflow file at the tag is what GitHub executes for the release.

### 7. Push In The Right Order

Recommended order:

1. push `main`
2. push the recreated tag

This ensures the release commit exists on the branch before the tag-triggered workflow reruns.

### 8. Finish With Final Verification

Confirm:

- the branch push succeeded
- the remote tag now points at the corrected commit
- the workflow rerun is using the updated release file

## Output Contract

A successful run should leave behind:

- a release workflow that supports both Trusted Publishing and token fallback
- a clean commit containing the release-recovery fix
- a remote tag attached to the corrected workflow snapshot
- a clear record that token fallback is temporary and Trusted Publishing remains the preferred path

## Decision Guardrails

- If `twine check` fails, stop and fix metadata before touching auth.
- If the repo must preserve tag immutability, do not move the tag; create a new version instead.
- If the token secret is present, make fallback explicit rather than trying to infer partial PyPI registration state.
- If the release is already public and consumers may rely on the old tag meaning, call out the retag clearly.

## Common Failure Modes

- assuming a PyPI 400 means bad metadata without checking the artifact
- adding token auth but forgetting to commit the workflow before rerunning the release
- rerunning the release from the old tag, which still points at the broken workflow snapshot
- permanently switching to tokens and forgetting to return to Trusted Publishing
- mixing unrelated code changes into the release-recovery commit

## References

- Command patterns: [references/command_patterns.md](./references/command_patterns.md)
