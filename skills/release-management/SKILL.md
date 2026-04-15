---
name: release-management
description: Execute clean Atulya releases with preflight validation, version bumping, SDK regeneration, docs deployment verification, and recovery from failed release/doc workflows. Use when shipping patch/minor releases, tagging versions, or debugging why release/docs did not publish.
---
# Release Management

Use this skill for end-to-end Atulya releases (`0.x.y`) with high reliability and low token usage.

## Default Mode

- Prefer deterministic scripts over ad-hoc edits.
- Run validations before tag/push.
- Treat release and docs as separate delivery checks.
- For patch releases (`x.y.z`, `z > 0`), update existing docs version line (for example `0.8.z` updates `version-0.8` docs).

## Fast Decision Tree

1. **Need new release tag?**
   - Yes -> run full preflight + version bump + regenerate + commit + tag + push.
2. **Release succeeded but docs site stale?**
   - Check docs workflow trigger path match and run state.
   - If no run, push a tiny docs-only commit or trigger `workflow_dispatch`.
3. **Tag already exists and failed previously?**
   - Do not reuse old tag.
   - Cut next patch (`0.8.3` after failed `0.8.2`).

## Clean Release Procedure

Run from repo root.

### 0) Pre-checks

```bash
git fetch origin
git pull --ff-only origin main
git status -sb
git branch --show-current
git tag -l "v<version>"
```

Requirements:
- On `main`
- Clean working tree
- No existing `v<version>` tag

### 1) Validate release lane first

```bash
./scripts/release-preflight-v0800.sh <version>
```

If it fails:
- Fix root cause first (do not tag).
- Re-run until green.

### 2) Update versions + docs + generated artifacts

Preferred scripted path (fast path):

```bash
./scripts/release.sh <version>
```

Note:
- `release.sh` is convenient, but it commits with `--no-verify`.
- For strict governance, use manual lane + explicit lint/build checks before commit/tag.

If you are doing controlled/manual release prep instead:

```bash
./scripts/update-docs-version.sh <version>
./scripts/generate-openapi.sh
./scripts/generate-clients.sh
```

Then verify:

```bash
./scripts/hooks/lint.sh
cd atulya-cli && cargo check && cd ..
npm run build --workspace=atulya-docs
npm run build --workspace=atulya-control-plane
```

### 3) Commit release payload

```bash
git add -A
git commit -m "Release v<version>"
```

### 4) Tag and push

```bash
git tag -a v<version> -m "Release v<version>"
git push origin main
git push origin v<version>
```

### 5) Verify GitHub workflows

Check:
- Release workflow for tag (`.github/workflows/release.yml`)
- Docs workflow (`.github/workflows/deploy-docs.yml`)
- GitHub Release page for `v<version>` assets

Release should be green before announcing.

## Failure Playbook (Common)

### A) Release run fails on Rust CLI build

Symptoms:
- `release-rust-cli` job fails in release workflow.

Actions:
1. Reproduce locally:
   ```bash
   cd atulya-cli && cargo check
   ```
2. Regenerate clients and re-check:
   ```bash
   cd /path/to/repo
   ./scripts/generate-clients.sh
   cd atulya-cli && cargo check
   ```
3. Commit fix on `main`.
4. Cut next patch tag (never mutate existing failed tag).

### B) Release succeeded, docs did not update

Symptoms:
- Release run green, docs site still old.
- No new docs workflow run.

Likely cause:
- Push event did not trigger docs workflow path filter.
- Very large release commit may miss expected path-trigger behavior.

Actions:
1. Confirm docs workflow trigger:
   - `push` on `main`
   - paths include `atulya-docs/**`
2. Push tiny docs-only commit (preferred) OR run `workflow_dispatch`.
3. Re-verify docs deployment run success.

### C) Tag exists but run failed

Do not re-use tag.

Use next patch:
- failed `v0.8.2` -> ship `v0.8.3`

### D) Generated SDK drift after version bump

Actions:
1. Re-run generation in order:
   ```bash
   ./scripts/generate-openapi.sh
   ./scripts/generate-clients.sh
   ```
2. Re-run lint/build checks.
3. Commit regenerated outputs together.

## Required Release Invariants

- `release-preflight-v0800.sh` passes.
- `./scripts/hooks/lint.sh` passes.
- `cargo check` passes for `atulya-cli`.
- Docs build passes.
- Control plane build passes.
- Tag is new and points to validated commit.

## Output Template For Agents

After release operations, report:

1. Version/tag shipped
2. Commit SHA
3. Release workflow URL + status
4. Docs workflow URL + status
5. Any follow-up action required

## Deep Reference

For full command matrix, troubleshooting, and recovery workflows, read:

- [release-runbook.md](release-runbook.md)
