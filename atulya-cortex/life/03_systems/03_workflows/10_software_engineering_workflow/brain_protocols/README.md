# Brain Protocols

## Overview
Brain Protocols are Atulya's reusable operating procedures for high-risk or high-value engineering work.
They play a role similar to external "skills", but they now live inside the `life/` index as procedural memory learned through real software operations.

Use a Brain Protocol when the work needs:

- a repeatable decision flow
- explicit safety checks
- exact verification steps
- a clean split between the main procedure and deeper references

## Standard Shape
Each protocol lives in its own folder and uses `BRAIN.md` as the entrypoint:

```text
protocol_name/
├── BRAIN.md
├── references/
└── assets/
```

## Design Rules

- `BRAIN.md` is required and should explain when to use the protocol, when not to use it, and the end-to-end workflow.
- `references/` is optional and should hold deeper material such as command patterns, recovery guides, or examples.
- `assets/` is optional and should only contain templates or files the protocol actively uses.
- Keep the main `BRAIN.md` readable under pressure. Put detail in references, not in the critical path.
- Prefer protocols for workflows that are dangerous, expensive, brand-sensitive, or operationally brittle.

## Naming

- Folder names should be lowercase with underscores.
- Choose names that describe the operation, not the incident.
- Prefer names like `git_history_rewrite_and_branch_realignment` over names tied to one repo mistake.

## Creating A New Protocol

1. Copy `./_template/BRAIN.md` into a new protocol folder.
2. Write the trigger conditions first so the protocol is easy to select under pressure.
3. Keep the main flow operational and short enough to execute live.
4. Move dense command lists, edge cases, and recovery notes into `references/`.
5. Add the new protocol to the list below so it becomes discoverable.

## Current Protocols

- `dependency_drift_and_reproducible_toolchains`
  Use when a stable workflow starts warning or behaving differently after reinstall or rebuild and the real fix is to pin and verify the toolchain, not just quiet the symptom.

- `semantic_read_model_salvage_and_retain_backed_validation`
  Use when a semantic or graph-heavy rewrite helps one strong example but threatens the existing subsystem contract, and the right response is to salvage the insight, rebuild behind contract tests, and add a tiny retain-backed evaluation lane.

- `git_history_rewrite_and_branch_realignment`
  Use when incorrect or sensitive content has landed in Git history and must be removed from one or more branches without losing local work.

- `pypi_release_fallback_and_tag_realignment`
  Use when a tag-triggered Python release is blocked by PyPI trusted-publisher setup, token fallback must be enabled temporarily, and the release tag needs to be reattached so the rerun uses the corrected workflow snapshot.
