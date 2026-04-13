# Versioned Docs Can Hide Current Sidebar And Landing Page Changes Until Release Sync

Date: 2026-04-13
Repo: atulya
Area: docs, Docusaurus versioning, release hygiene, sidebar visibility

## Trigger

The Codebases docs were updated in the live source tree:

- new sidebar wiring in `sidebars.ts`
- a new `Codebases` docs section
- stronger landing-page placement in `docs/developer/index.md`

But when the site was inspected in the browser, the new Codebases sidebar entry still did not appear.

That created the impression that the docs UI work had not landed.

## Root Cause

The issue was not stale MDX source and not a broken sidebar definition.

The real problem was version context:

- the browser was showing the released `0.8` docs
- released docs use `versioned_sidebars/version-0.8-sidebars.json`
- `0.8` did not yet contain the new Codebases pages or sidebar structure
- the updated source lived in `docs/` and `sidebars.ts`, which represent the current or next version

So the source was correct, but the viewed versioned snapshot was older.

## Better Debug Pattern

When docs UI changes seem missing, check version context before changing code again.

Use this order:

1. confirm which docs version is selected in the UI
2. inspect `versions.json`
3. compare `sidebars.ts` against the relevant `versioned_sidebars/version-*.json`
4. confirm whether the new docs exist in `docs/` only or also in `versioned_docs/version-*`

If the selected version is a released snapshot, current-source sidebar edits alone will not appear there.

## Repo-Specific Rule

In this repo:

- `docs/` plus `sidebars.ts` define the current or next version
- released versions are frozen into:
  - `versioned_docs/version-*`
  - `versioned_sidebars/version-*-sidebars.json`
- patch releases sync current docs into an existing major-minor version

That means a release like `0.8.1` refreshes the visible `0.8` docs rather than creating a separate `0.8.1` docs lane.

## Failure Modes To Avoid

- assuming a missing released sidebar item means the source patch failed
- editing current docs repeatedly when the real problem is the selected released version
- forgetting that versioned sidebars are separate artifacts from `sidebars.ts`
- validating only the local dev build while stakeholders are browsing a released version

## Practical Release Rule

If the goal is "make the released docs show the new section," do not stop at updating `docs/`.

Also ensure the release flow syncs the current docs into the target versioned snapshot.

For this repo, that means using the docs version script with the intended patch release so the versioned docs and versioned sidebar are refreshed together.

## Expected Benefits

- faster root-cause analysis when docs navigation appears stale
- fewer unnecessary source edits
- better alignment between local validation and what operators actually browse
- cleaner release conversations around "current" versus "released" docs state

## Cortex Links

- Related publish lesson: [validated_work_should_be_rebased_carefully_when_main_moves_during_publish](./2026-04-13_validated_work_should_be_rebased_carefully_when_main_moves_during_publish.md)
- Related protocol: [full_stack_feature_rollout_and_batch_publish](../../03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/full_stack_feature_rollout_and_batch_publish/BRAIN.md)
- Root brain contract: [BRAIN.md](../../../../../BRAIN.md)
