# Command Patterns

These patterns support the `dependency_drift_and_reproducible_toolchains` protocol.

## Inspect The Declared Range

```bash
sed -n '1,220p' atulya-docs/package.json
sed -n '1,220p' package.json
```

## Inspect The Concrete Resolution

```bash
rg -n '@easyops-cn/docusaurus-search-local' package-lock.json -n -A3 -B2 -S
```

## Refresh The Lockfile

```bash
npm install
```

## Verify Workspace Lockfile Ownership

```bash
sed -n '1,120p' .github/workflows/deploy-docs.yml
rg -n 'babel-plugin-polyfill-corejs2|resolved|version' package-lock.json -n -A4 -B2 -S
```

If CI runs `npm ci --workspace=<name>` but `actions/setup-node` points `cache-dependency-path` at the root `package-lock.json`, treat the root lockfile as the source of truth for the workspace install too.

In that setup:

- regenerate the root lockfile from the repo root
- verify the concrete replacement in the root lockfile
- rerun the exact workspace install command that failed in CI

## Verify The Production Path

```bash
npm --prefix atulya-docs run build
```

## Verify The Dev Path

```bash
./scripts/dev/start-docs.sh
```

## Good Heuristics

- Pin brittle docs and frontend infrastructure dependencies exactly when patch drift changes behavior.
- In monorepos, pair the workspace pin with a root override when hoisting or shared resolution can reintroduce drift.
- Treat "dev warning only" and "production break" as different severity classes until both paths are tested.
- For `npm` workspaces, the lockfile that matters is the one referenced by CI, not the folder you happen to be fixing.
- If a docs deploy workflow is path-filtered to `atulya-docs/**`, a lockfile-only dependency fix may still need either a docs change or a manual `workflow_dispatch` to actually deploy.
