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
