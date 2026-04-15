# Atulya Release Runbook (Detailed)

This runbook is optimized for reliable execution by both humans and coding agents.

## 1) Scope And Philosophy

Release quality is governed by four gates:

1. **Code gate**: lint/type/build checks pass.
2. **Contract gate**: generated OpenAPI and SDK clients are consistent with code.
3. **Packaging gate**: version metadata is aligned across Python/Node/Rust/Helm.
4. **Delivery gate**: GitHub release workflow and docs deployment both succeed.

Never skip a gate.

## 2) Release Types

- **Patch** (`0.8.3`):
  - update current minor docs line (`version-0.8`)
  - no new docs major/minor snapshot directory
- **Minor/Major** (`0.9.0`, `1.0.0`):
  - create a new docs version snapshot line

## 3) Standard Command Sequence

Use this exact order.

### Step 1: Environment and repo state

```bash
git fetch origin
git pull --ff-only origin main
git status -sb
git branch --show-current
git tag -l "v<version>"
```

Expected:
- branch `main`
- no uncommitted changes
- no pre-existing tag `v<version>`

### Step 2: Release preflight

```bash
./scripts/release-preflight-v0800.sh <version>
```

This checks migration chain, key tooling, and Rust CLI contract checks in this repo line.

### Step 3: Version + docs + generated artifacts

Preferred one-command path:

```bash
./scripts/release.sh <version>
```

This script handles:
- version updates across packages
- docs version sync/snapshot via `update-docs-version.sh`
- OpenAPI generation
- SDK generation

Important:
- `release.sh` commits with `--no-verify`.
- If your release policy requires hook-enforced commits, use manual lane:
  - run version/docs/gen commands
  - run validation gate commands
  - commit without `--no-verify`

### Step 4: Explicit validations (must be green)

```bash
./scripts/hooks/lint.sh
cd atulya-cli && cargo check && cd ..
npm run build --workspace=atulya-docs
npm run build --workspace=atulya-control-plane
```

### Step 5: Commit/tag/push

```bash
git add -A
git commit -m "Release v<version>"
git tag -a v<version> -m "Release v<version>"
git push origin main
git push origin v<version>
```

### Step 6: Delivery verification

Confirm both workflows:
- `.github/workflows/release.yml`
- `.github/workflows/deploy-docs.yml`
- GitHub Releases page contains `v<version>` with expected assets

## 4) Failure Modes and Exact Recovery

### Failure Mode A: Tag workflow fails

#### A1) Rust CLI or SDK contract failure

Symptoms:
- Release job fails on Rust client/CLI build.

Recovery:
```bash
./scripts/generate-clients.sh
cd atulya-cli && cargo check && cd ..
./scripts/hooks/lint.sh
```

Then:
- commit fix on `main`
- ship next patch tag

Important:
- Never force-update a failed existing release tag.

---

### Failure Mode B: Docs site didn’t update but release succeeded

Symptoms:
- Release is green.
- Docs workflow absent for new SHA.
- Site still shows older content.

Checks:
1. Verify docs workflow trigger:
   - push on `main`
   - paths includes `atulya-docs/**`
2. Verify new commit actually includes docs path changes.
3. Verify docs workflow run exists for same `head_sha`.

Recovery options:

Option 1 (best): tiny docs-only commit
```bash
git commit --allow-empty -m "docs: trigger pages deploy"
git push origin main
```

Better than empty commit: touch docs content intentionally (for example update changelog wording), then push.

Option 2: manual run
- trigger `workflow_dispatch` for docs workflow.

---

### Failure Mode C: Existing failed tag (for example `v0.8.2`)

Problem:
- Tag immutable in practice for release correctness.

Recovery:
1. Fix on `main`.
2. bump patch (`0.8.3`).
3. tag new release (`v0.8.3`).

---

### Failure Mode D: Path-filter docs trigger missed on giant commit

Problem:
- Huge release commits can make docs trigger behavior brittle.

Recovery and prevention:
- keep docs deployment trigger as separate small commit/push
- or run docs workflow manually post-release
- optional workflow hardening: reduce dependency on path-only trigger by allowing manual dispatch always

## 5) Pre-Release Checklist (Copy/Paste)

```markdown
- [ ] On main branch
- [ ] Working tree clean
- [ ] release-preflight passes
- [ ] versions updated to target
- [ ] openapi regenerated
- [ ] clients regenerated
- [ ] lint passes
- [ ] cargo check passes
- [ ] docs build passes
- [ ] control-plane build passes
- [ ] release commit created
- [ ] tag created and pushed
- [ ] release workflow green
- [ ] docs workflow green
```

## 6) Post-Release Checklist

```markdown
- [ ] GitHub Release page exists for v<version>
- [ ] package publication jobs succeeded (PyPI/npm/GHCR/Helm as applicable)
- [ ] docs.atulya.eightengine.com reflects new changelog/version content
- [ ] release summary posted to team/channel
```

## 7) Agent Reporting Format (Token-Efficient)

Use this exact compact structure:

```markdown
Release: v<version>
Commit: <sha>
Release Workflow: <status> - <url>
Docs Workflow: <status> - <url>
Docs Site: <updated|stale>
Action Needed: <none|one-line fix>
```

## 8) Notes For Multi-OS/Container Environments

- If running in Docker-based developer setups, execute release commands inside the release-capable container that has git/toolchain credentials and SDK build dependencies.
- Keep path usage POSIX style in scripts (`/`), even when host machine is Windows.

