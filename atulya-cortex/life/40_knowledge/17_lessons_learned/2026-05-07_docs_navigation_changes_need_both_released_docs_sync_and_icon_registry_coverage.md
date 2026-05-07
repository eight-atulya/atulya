# Docs Navigation Changes Need Both Released Docs Sync And Icon Registry Coverage

Date: 2026-05-07
Repo: atulya
Area: docs, Docusaurus, release hygiene, sidebar runtime

## Trigger

Two docs-facing issues showed up in one rollout:

- the new Memory Repos docs page and blog links looked correct in source but failed in the public docs build
- the Brain API Map sidebar icon rendered as a broken empty box in some browsers

## Root Cause

These were two different failures:

1. released docs drift

- this repo publishes released docs from `versioned_docs/version-*` and `versioned_sidebars/version-*-sidebars.json`
- adding a new page only in `docs/` and `sidebars.ts` is not enough when the public site resolves against a released train like `0.8`
- the blog and sidebar were pointing at a route that did not exist in the released snapshot yet

2. icon registry drift

- the sidebar config used `customProps.icon: 'lu-map'`
- the swizzled docs sidebar wrapper did not define `lu-map` in its `ICON_MAP`
- unknown icon keys fell through to the image fallback path, so `"lu-map"` was treated like an image URL instead of an icon id

## Better Debug Pattern

When docs navigation or docs UI looks broken, check both the content layer and the runtime layer:

1. confirm which docs version the build or browser is actually serving
2. check whether the page exists in both `docs/` and the relevant `versioned_docs/version-*`
3. compare `sidebars.ts` with the relevant `versioned_sidebars/version-*-sidebars.json`
4. if a sidebar icon is broken, inspect the swizzled icon registry before changing SVG assets
5. verify whether the fallback path is treating an icon id like an image source

## Repo-Specific Rule

For this repo:

- public released docs may require mirroring changes into the active released version snapshot
- sidebar icon keys are only valid if they exist in `atulya-docs/src/theme/DocSidebarItem/Link/index.tsx`
- unknown icon ids should fail gracefully as generic icons, not as broken images

## Failure Modes To Avoid

- fixing only `docs/` when the released docs train is what users actually browse
- assuming a broken sidebar glyph means the SVG asset itself is bad
- letting icon-key typos silently render through the image fallback path
- validating blog links only against `current` docs when the build resolves against a released version

## Practical Rule

For docs navigation or landing-page changes:

- update `docs/` and `sidebars.ts`
- if the page must exist in the released train, update the matching `versioned_docs/version-*` and `versioned_sidebars/version-*-sidebars.json`
- if a sidebar item uses a custom icon key, confirm the key is registered in the sidebar icon wrapper
- keep the icon fallback restricted to real image paths like `/`, `./`, `../`, `http`, `https`, or `data:`

## Expected Benefits

- faster root-cause analysis for broken docs navigation
- fewer false SVG hunts when the bug is really a missing icon registry entry
- better parity between local docs edits and what the public site serves
- safer future docs work when new sections ship alongside sidebar icons

## Cortex Links

- Related lesson: [versioned_docs_can_hide_current_sidebar_and_landing_page_changes_until_release_sync](./2026-04-13_versioned_docs_can_hide_current_sidebar_and_landing_page_changes_until_release_sync.md)
- Related protocol: [full_stack_feature_rollout_and_batch_publish](../../03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/full_stack_feature_rollout_and_batch_publish/BRAIN.md)
- Root brain contract: [BRAIN.md](../../../../../BRAIN.md)
