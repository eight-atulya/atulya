# Atulya System Testing — Deep Reference

Companion to [SKILL.md](SKILL.md). Read on demand when SKILL.md points here.

## Per-surface command matrix

### Python (atulya-api)

| Goal | Command |
| --- | --- |
| Single test | `( cd atulya-api && uv run pytest -p no:xdist --timeout=180 tests/test_X.py::test_Y -v )` |
| Single file | `( cd atulya-api && uv run pytest -p no:xdist --timeout=180 tests/test_X.py )` |
| All tests, sequential | `( cd atulya-api && uv run pytest -p no:xdist --timeout=180 )` |
| All tests, parallel (only when LLM is fast/mocked) | `( cd atulya-api && uv run pytest --timeout=60 )` |
| Lint only | `( cd atulya-api && uv run ruff check . )` |
| Format only | `( cd atulya-api && uv run ruff format . )` |
| Type check | `( cd atulya-api && uv run ty check atulya_api )` |
| Capture failures to file | `... pytest ... 2>&1 \| tee /tmp/pytest.log \| tail -200` |

### Rust (atulya-cli + atulya-clients/rust)

| Goal | Command |
| --- | --- |
| Type-check client only | `( cd atulya-clients/rust && cargo check )` |
| Type-check CLI (also rebuilds client) | `( cd atulya-cli && cargo check )` |
| Build CLI release binary | `( cd atulya-cli && cargo build --release )` |
| Run CLI tests | `( cd atulya-cli && cargo test )` |
| Format | `( cd atulya-cli && cargo fmt )` |
| Lint | `( cd atulya-cli && cargo clippy -- -D warnings )` |

Always `. ~/.cargo/env` first if cargo isn't on PATH yet.

### TypeScript (atulya-clients/typescript)

| Goal | Command |
| --- | --- |
| Build (tsc) | `( cd atulya-clients/typescript && npm run build )` |
| Direct tsc | `( cd atulya-clients/typescript && npx tsc )` |
| Watch | `( cd atulya-clients/typescript && npx tsc --watch )` |

### Control plane (atulya-control-plane)

| Goal | Command |
| --- | --- |
| Type-check | `( cd atulya-control-plane && npx tsc --noEmit )` |
| Lint | `( cd atulya-control-plane && npm run lint )` |
| Dev server | `( cd atulya-control-plane && npm run dev )` (port 9999) |
| Production build | `( cd atulya-control-plane && npm run build )` |

There is **no** `typecheck` script — `npx tsc --noEmit` is the canonical way.

### OpenAPI + clients

| Goal | Command |
| --- | --- |
| Spec only (no clients) | `bash scripts/generate-openapi.sh` |
| All four clients (needs Docker + cargo + go) | `sg docker -c '. ~/.cargo/env && bash scripts/generate-clients.sh'` |
| Docs skill (mirrors `atulya-docs/docs/` to `skills/atulya-docs/references/`) | `bash scripts/generate-docs-skill.sh` |

## Known script bugs (already patched in this tree)

These were caught and fixed during the initial Linux bring-up. If you re-clone
or reset, re-apply.

### `scripts/generate-clients.sh` line ~84

```bash
# BAD (works on macOS BSD mktemp, fails on GNU mktemp):
CLIENT_OPENAPI_SPEC="$(mktemp -t atulya-openapi-client-spec)"

# GOOD (works on both):
CLIENT_OPENAPI_SPEC="$(mktemp -t atulya-openapi-client-spec.XXXXXX)"
```

GNU mktemp requires explicit X's; BSD mktemp tolerates either. The `.XXXXXX`
suffix is the portable form.

### `scripts/generate-clients.sh` `run_openapi_generator()`

In Docker mode, the function used to splat all caller args into `docker run`,
so openapi-generator-cli flags like `-o` and `-c` were interpreted by docker
itself (`unknown shorthand flag: 'o' in -o`). Fix: split caller args at a `--`
separator into "docker args" (before `--`) and "generator args" (after `--`).
Both Python and Go callers now insert `--` between `-v` mounts and `-o`/`-c`.

## Post-regen drift

After `scripts/generate-clients.sh` succeeds, four things commonly need
hand-fixups (because the generators can't faithfully express recursive or
inlined types):

### 1. TypeScript: missing `TagGroup` alias

`@hey-api/openapi-ts` inlines `oneOf` unions per property instead of emitting
a named alias. The fix lives in `atulya-clients/typescript/src/index.ts`:

```ts
// Re-export the four leaf types from the regenerated bundle, then synthesize
// the union alias by hand. Downstream code imports { TagGroup } from this file.
export type TagGroup = TagGroupLeaf | TagGroupAnd | TagGroupOr | TagGroupNot;
```

### 2. Rust: recursive `TagGroup` enum

`progenitor` cannot express the boxed-recursive `TagGroup` cleanly, so the
enum is hand-maintained in `atulya-clients/rust/src/types.rs`. If a regen
overwrites it, the Rust client builds but `atulya-cli` fails to compile
against it. Re-apply the `Box<TagGroup>` variants and re-run
`( cd atulya-cli && cargo check )`.

### 3. Python: usually clean

Python codegen handles the discriminated union correctly via Pydantic. No
hand-fixup typically needed. If the import path drifts, check the
`openapi-generator-config.yaml` in `atulya-clients/python/`.

### 4. Go: inlined inner types

The Go generator emits `RecallRequestTagGroupsInner` as a wrapper struct; this
is fine for client use but verbose. No fix-up required unless a downstream
consumer expects a specific name.

## Smoke-test field reference

The fields most worth grepping after a feature port:

| Feature | Fields to grep |
| --- | --- |
| Retain append mode | `update_mode` |
| Tag groups | `tag_groups`, `TagGroup`, `TagGroupLeaf`, `TagGroupAnd`, `TagGroupOr`, `TagGroupNot` |
| Observation cap | `max_observations_per_scope`, `observation_scopes` |
| Hindsight leak audit | `hindsight` (must return 0) |

## File map of generated artifacts

| Surface | Generated file | Hand-maintained file |
| --- | --- | --- |
| OpenAPI | `atulya-docs/static/openapi.json` | (none — fully generated) |
| Python | `atulya-clients/python/atulya_client_api/**` | `atulya_client.py` (wrapper, preserved by script) |
| TypeScript | `atulya-clients/typescript/generated/types.gen.ts` | `src/index.ts`, `src/atulya-client.ts` |
| Rust | `atulya-clients/rust/src/lib.rs` (via `build.rs`) | `src/types.rs` (recursive enums) |
| Go | `atulya-clients/go/model_*.go`, `api_*.go` | (none — patches applied in-script for missing `os` import) |

## Pytest verbosity ladder

When investigating a failure, escalate verbosity in this order — each level
gives more signal but more noise:

```bash
# 1. Quiet — pass/fail counts only
uv run pytest -p no:xdist --timeout=180 -q

# 2. Verbose — test names and outcomes
uv run pytest -p no:xdist --timeout=180 -v

# 3. With short tracebacks on failure
uv run pytest -p no:xdist --timeout=180 -v --tb=short

# 4. Full tracebacks + locals
uv run pytest -p no:xdist --timeout=180 -v --tb=long --showlocals

# 5. Stop on first failure (fastest iteration)
uv run pytest -p no:xdist --timeout=180 -v -x

# 6. Show stdout/logs even on success
uv run pytest -p no:xdist --timeout=180 -v -s
```

## When the LLM-backed tests are flaky

Several integration tests call the LLM at `ATULYA_LLM_BASE_URL`. Symptoms:

- `slow llm call: ... time=20.126s` log lines
- Tests pass sequentially but fail under xdist
- Per-test 60 s timeout fires mid-consolidation

Mitigations, in increasing order of invasiveness:

1. **Always run sequentially**: `-p no:xdist`
2. **Bump timeout**: `--timeout=180` or `--timeout=300`
3. **Skip LLM tests during fast-iteration**: `-k 'not consolidation and not retain'`
4. **Mock the LLM**: see `tests/test_observation_cap.py` for the standard
   mocking patterns (`AsyncMock` with hand-built `_consolidate_batch_with_llm`
   return values).

## Reading the terminal log when xdist is hiding tracebacks

Pytest under xdist only shows pass/fail markers in real time; tracebacks land
at the very end of the log. Useful filters:

```bash
# Failure summary (works even if log is truncated)
grep -E '^(FAILED|ERROR)' /tmp/pytest.log | sort -u

# Just counts
grep -cE 'PASSED' /tmp/pytest.log
grep -cE 'FAILED|ERROR' /tmp/pytest.log
grep -cE 'SKIPPED' /tmp/pytest.log

# Re-run only the failures sequentially with full tracebacks
( cd atulya-api && uv run pytest -p no:xdist --timeout=180 \
  --last-failed -v --tb=long )
```

## When to give up and ask the user

- The LLM at `ATULYA_LLM_BASE_URL` is unreachable (`Connection refused`).
- The Postgres at `DATABASE_URL` (default `localhost:5556`) is unreachable.
- A hand-maintained type was overwritten and you can't tell from context what
  the original looked like.
- Lint fails on a file you didn't touch (probably stale; ask before "fixing").
- Tests fail in a way that requires a database migration the user hasn't run.
