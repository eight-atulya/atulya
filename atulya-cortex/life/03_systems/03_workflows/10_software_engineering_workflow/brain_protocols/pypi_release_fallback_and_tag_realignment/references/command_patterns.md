# Command Patterns

These patterns support the `pypi_release_fallback_and_tag_realignment` protocol.

## Verify Package Artifacts

```bash
cd atulya-api
uv build --out-dir dist-check
cd ..
uvx twine check atulya-api/dist-check/*
```

## Inspect The Release Workflow

```bash
nl -ba .github/workflows/release.yml | sed -n '1,140p'
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/release.yml"); puts "YAML OK"'
```

## Inspect The Current Release Tag

```bash
git show --stat --summary v0.8.0
git ls-remote --tags origin 'v0.8.0'
```

## Recreate The Tag On The Correct Commit

```bash
git tag -d v0.8.0
git tag -a v0.8.0 -m "Atulya 0.8.0: meaningful memory for humans and AI"
```

## Push In The Right Order

```bash
git push origin main
git push origin v0.8.0
```

## Good Heuristics

- If the workflow changed, the tag usually has to move too.
- Keep OIDC as the default and token upload as the emergency lane.
- Validate the artifact before changing auth assumptions.
