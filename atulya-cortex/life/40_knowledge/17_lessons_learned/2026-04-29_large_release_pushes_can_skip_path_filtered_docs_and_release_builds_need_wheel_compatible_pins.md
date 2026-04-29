# Large Release Pushes Can Skip Path-Filtered Docs And Release Builds Need Wheel-Compatible Pins

Date: 2026-04-29
Repo: atulya
Area: release engineering, GitHub Actions, docs deployment, Docker packaging

## Trigger

The `v0.8.4` release tag published most artifacts successfully, but the Docker release lane failed and the docs site did not update after the release train landed on `main`.

## Root Cause

Two separate release-facing issues overlapped:

- the Docker image build resolved dependencies directly from `atulya-api/pyproject.toml`, which allowed `tree-sitter-language-pack` to float to `1.6.x`
- `tree-sitter-language-pack 1.6.x` did not provide the CPython 3.11 Linux wheel needed by the release image build
- the docs deploy workflow used `on.push.paths`, but the release commit changed 481 files and the first `atulya-docs/` path did not appear until file 436
- GitHub evaluates path filters against only the first 300 changed files for these diff checks, so the docs workflow was silently skipped even though docs files changed

## Better System Design

For release workflows:

1. pin dependencies to a range that is known to publish compatible wheels for the runtime used in release images
2. do not rely on path-filtered `push` workflows for large release trains when docs, generated assets, or release collateral may land late in the changed-file list
3. prefer unconditional `main` docs deployment over a fragile filter when the docs build is lightweight enough

## Applied Pattern

The repair that stabilized this path was:

- tighten `tree-sitter-language-pack` to `>=1.5.0,<1.6.0` in `atulya-api/pyproject.toml`
- refresh `uv.lock` so the lockfile and package metadata agree
- remove the `paths` gate from `.github/workflows/deploy-docs.yml` so all pushes to `main` can publish docs

## Practical Rule

If a release push touches hundreds of files, assume GitHub path filters can miss the intended paths unless you have proven the matching files land early in the diff.

If a release image installs from `pyproject.toml` instead of a repo-wide lock strategy, treat wheel availability for the exact runtime as part of the release contract.

## Validation Rule

For this class of release fix:

- inspect the failing Actions job logs before editing
- prove the dependency graph in a fresh environment that mirrors the Docker install path
- run the docs production build locally
- run the repo lint flow before pushing

## Expected Benefits

- Docker release lanes fail less often due to upstream wheel drift
- docs deploys do not silently disappear on broad release pushes
- future release triage separates artifact publication failures from docs deployment trigger failures more quickly

## Cortex Links

- Workflow protocol: [dependency_drift_and_reproducible_toolchains](../../03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/dependency_drift_and_reproducible_toolchains/BRAIN.md)
- Workflow protocol: [full_stack_feature_rollout_and_batch_publish](../../03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/full_stack_feature_rollout_and_batch_publish/BRAIN.md)
