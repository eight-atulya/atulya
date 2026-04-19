# Atulya Dev Flow — Concrete Playbooks

Companion to [SKILL.md](SKILL.md). Each playbook is a recipe for a recurring
end-to-end task in this repo. Copy the checklist; tick as you go.

## Playbook 1 — Add a new configurable bank setting

Use when the user wants a new tunable knob (e.g. `max_observations_per_scope`,
`retain_chunk_size`).

```
- [ ] 1. Define field in atulya-api/atulya_api/config.py:
        - add to AtulyaConfig BaseSettings
        - add ENV_<NAME> + DEFAULT_<NAME> module constants
        - add to get_configurable_fields() return value
        - add env loader entry in from_env()
        - add range/sanity check in _validate_fields()
- [ ] 2. Add UI input in atulya-control-plane/src/components/bank-config-view.tsx:
        - add to ObservationsEdits / RetainEdits / etc. type
        - add to observationsSlice() / retainSlice() etc. mapping
        - add a <FieldRow> with appropriate <Input> / <Select>
- [ ] 3. Wire field into the engine logic that consumes it
        (atulya-api/atulya_api/engine/...).
        Add unit/integration tests in atulya-api/tests/.
- [ ] 4. Update docs:
        - atulya-docs/docs/developer/configuration.md (env var table row)
        - bash scripts/generate-docs-skill.sh
- [ ] 5. Update test_hierarchical_config.py:
        - bump len(configurable) assertion (currently 26)
        - bump security guard "len(config) < 30"
- [ ] 6. Run targeted tests:
        ( cd atulya-api && uv run pytest -p no:xdist --timeout=180 \
          tests/test_hierarchical_config.py \
          tests/test_<your_feature>.py -v )
- [ ] 7. Lint: ./scripts/hooks/lint.sh
- [ ] 8. Control-plane typecheck:
        ( cd atulya-control-plane && npx tsc --noEmit )
- [ ] 9. Hindsight grep audit
- [ ] 10. Report
```

**Why this many steps?** Configurable fields touch four loosely-coupled
surfaces (config object, env loader, validator, UI, docs, security tests). A
"working" change that omits any one becomes a silent bug: the UI lets users
set a value the server ignores, or the field leaks to credential checks, or
nobody knows the env var exists.

## Playbook 2 — Add a new API endpoint

Use when the user wants a new route (e.g. `POST /v1/banks/{id}/foo`).

```
- [ ] 1. Define request/response Pydantic models in atulya-api/atulya_api/models/
- [ ] 2. Add the route in atulya-api/atulya_api/api/http.py:
        - decorator with full path and tags
        - dependency-inject memory engine, request context, etc.
        - call into engine layer (don't do logic in the handler)
- [ ] 3. Implement engine logic in atulya-api/atulya_api/engine/<module>.py
- [ ] 4. Add integration test in atulya-api/tests/test_<area>.py
        using TestClient or httpx.AsyncClient
- [ ] 5. Run targeted test sequentially
- [ ] 6. Lint
- [ ] 7. Regenerate spec + clients:
        sg docker -c '. ~/.cargo/env && bash scripts/generate-clients.sh'
- [ ] 8. Verify generated artifacts:
        - atulya-docs/static/openapi.json contains the new path
        - atulya-clients/python/atulya_client_api/api/<area>_api.py
          has the new method
        - same in TS, Go, Rust
- [ ] 9. Rebuild dependents:
        ( cd atulya-clients/typescript && npm run build )
        ( cd atulya-control-plane && npx tsc --noEmit )
        ( . ~/.cargo/env && cd atulya-cli && cargo check )
- [ ] 10. If the CLI should expose this endpoint, add a subcommand in
         atulya-cli/src/commands/<area>.rs
- [ ] 11. Update docs:
         - atulya-docs/docs/developer/api/<area>.mdx
         - bash scripts/generate-docs-skill.sh
- [ ] 12. MCP tool? If yes, register it in the MCP tool layer.
- [ ] 13. Hindsight grep
- [ ] 14. Report with the new endpoint URL + sample curl
```

## Playbook 3 — Port a feature from another repo

Use when the user says "port X from repo Y" (e.g. the recent
hindsight → atulya port).

```
- [ ] 1. Locate the source code in the donor repo. Read all files involved.
- [ ] 2. Map donor concepts → atulya concepts. List names, types, and
        public surfaces. Note any naming changes (donor "agent" ≈ atulya
        "bank"? donor "memory" ≈ atulya "fact"?).
- [ ] 3. Apply the change to atulya-api first (Pydantic models, routes,
        engine logic, tests). NEVER copy donor file structure 1:1 — use
        atulya's existing module layout.
- [ ] 4. Run Playbook 2 step 7 onward (regenerate clients, rebuild
        dependents, update CLI, docs, MCP).
- [ ] 5. CRITICAL: scrub every donor reference:
        grep -ric '<donor-name>' --include='*.{py,ts,tsx,rs,go,md,json,yaml,yml,sh}' \
          /home/atulya-agent/atulya-agent/atulya 2>/dev/null | grep -v ':0$'
        Must return empty before declaring done.
- [ ] 6. Add tests covering the new feature. Don't copy donor tests
        verbatim — port them to atulya's test fixtures (memory, request_context).
- [ ] 7. Run full system test suite (delegate to atulya-system-testing).
```

## Playbook 4 — Fix a script bug

Use when a script (`generate-clients.sh`, `release.sh`, `start.sh`, etc.)
fails on Linux but is reportedly working on macOS, or vice versa.

```
- [ ] 1. Reproduce locally with the exact failing command.
- [ ] 2. Read the script — note assumptions about toolchain (mktemp,
        readlink, sed -i, find -print0) that differ between BSD (macOS) and
        GNU (Linux).
- [ ] 3. Apply portable fix (StrReplace). Common patterns:
        - mktemp -t TEMPLATE → mktemp -t TEMPLATE.XXXXXX (GNU needs X's)
        - readlink -f → on macOS need coreutils greadlink or python3 inline
        - sed -i 's/x/y/' → sed -i'' 's/x/y/' (GNU and BSD differ)
        - find ... -print0 | xargs -0 → portable
- [ ] 4. Re-run the script end-to-end.
- [ ] 5. If the script wraps Docker, also test with `sg docker -c '...'`
        to ensure group-membership-aware behaviour.
- [ ] 6. Document the fix inline (comment in the script) AND in
        skills/atulya-system-testing/reference.md under "Known script bugs".
- [ ] 7. Report.
```

## Playbook 5 — Diagnose a "100 tests failed" surprise

Use when pytest claims a flood of failures after what should be a small
change.

```
- [ ] 1. Re-read the failure list. Are they ALL in the same general area
        (e.g. test_consolidation, test_retain) or scattered?
- [ ] 2. Check if pytest-xdist parallelism is on:
        head -20 atulya-api/pyproject.toml | grep -A2 'pytest'
- [ ] 3. Re-run ONE failing test sequentially:
        ( cd atulya-api && uv run pytest -p no:xdist --timeout=180 \
          tests/test_<x>.py::test_<y> -xv )
- [ ] 4. If it passes sequentially but fails in parallel: it's flake.
        Re-run the WHOLE suite sequentially:
        ( cd atulya-api && uv run pytest -p no:xdist --timeout=180 \
          2>&1 | tee /tmp/pytest.log | tail -200 )
- [ ] 5. If it still fails sequentially: read the actual traceback. Check:
        - Database state (was Postgres seeded? schema migrated?)
        - LLM connectivity (curl ATULYA_LLM_BASE_URL/v1/models)
        - Stale assertions (someone bumped a count and forgot to update
          the matching test)
- [ ] 6. Report findings. Distinguish "real regression" vs "infra flake"
        vs "stale test".
```

## Playbook 6 — Update an OpenAPI Pydantic model field

Use when the user wants to add a field to an existing request/response
(e.g. add `update_mode` to `MemoryItem`).

```
- [ ] 1. Locate the Pydantic model:
        Grep("class MemoryItem", path="atulya-api/")
- [ ] 2. Add the field with proper type, default, and Field(description=...).
        Match neighbouring field style.
- [ ] 3. If the field is optional with backwards-compatibility implications,
        default it to None and document the legacy behaviour.
- [ ] 4. Wire field through the consumer code paths. Use Grep to find
        every constructor of this model.
- [ ] 5. Add a test exercising the new field.
- [ ] 6. Run targeted test, lint.
- [ ] 7. Regenerate clients (Playbook 2 step 7).
- [ ] 8. Verify field landed via cross-client smoke test:
        for f in atulya-docs/static/openapi.json \
                 atulya-clients/python/atulya_client_api/models/memory_item.py \
                 atulya-clients/typescript/generated/types.gen.ts \
                 atulya-clients/go/model_<...>.go \
                 atulya-clients/rust/src/lib.rs; do
          grep -c '<new_field>' "$f" 2>/dev/null
        done
- [ ] 9. Update docs.
- [ ] 10. Report.
```

## Playbook 7 — Add a regression test for a bug fix

Use when the user reports a bug and you've found the fix.

```
- [ ] 1. Write the test FIRST (TDD-style):
        - Reproduce the bug as a failing assertion
        - Run it, confirm it fails for the expected reason
- [ ] 2. Apply the minimal fix.
- [ ] 3. Re-run the test, confirm it passes.
- [ ] 4. Run the rest of the relevant test file to make sure you
        didn't regress anything else.
- [ ] 5. Add a comment in the fix code citing the bug:
        # Fix for <symptom>: previously <wrong behaviour> because
        # <root cause>. See test_<file>.py::test_<name>.
- [ ] 6. Lint, report.
```

## Anti-playbook — what NOT to do

| Don't | Because |
| --- | --- |
| Run `pytest` without `-p no:xdist` against the local LLM | You'll get phantom failures and waste time chasing them |
| Edit a generated file (`types.gen.ts`, `oas_schemas_gen.go`, generated `.py`) | Next regen wipes it |
| Run `git commit` without explicit user instruction | Violates session safety rules |
| `sudo` anything in the agent shell | The agent shell can't prompt for password — fails |
| Use `cat <<EOF > file` to create a file | Always use `Write` |
| Use `sed -i` to "patch" a file | Always use `StrReplace` |
| Bump a test assertion silently when it fails | The assertion existed for a reason — flag it |
| Change unrelated code while in the middle of a feature | Stay scoped |
| Re-export removed donor names "for backwards compat" | This is a fresh repo — no shims |
| Read entire huge files (`http.py` is 7400 lines) front-to-back | Use `SemanticSearch` or `Grep` to scope first |

## Quick reference — most-used commands in this repo

```bash
# Repo root for all commands below:
cd /home/atulya-agent/atulya-agent/atulya

# Lint everything (parallel, fast)
./scripts/hooks/lint.sh

# Run a single Python test, sequential, full traceback
( cd atulya-api && uv run pytest -p no:xdist --timeout=180 \
  tests/test_<file>.py::test_<name> -xv )

# Run a single Python test file, sequential
( cd atulya-api && uv run pytest -p no:xdist --timeout=180 \
  tests/test_<file>.py )

# Type-check the Rust CLI against current Rust client
. ~/.cargo/env && ( cd atulya-cli && cargo check )

# Build the TypeScript client
( cd atulya-clients/typescript && npm run build )

# Type-check the control plane
( cd atulya-control-plane && npx tsc --noEmit )

# Regenerate OpenAPI spec only (no clients)
bash scripts/generate-openapi.sh

# Regenerate ALL four clients (needs Docker + cargo + go)
sg docker -c '. ~/.cargo/env && bash scripts/generate-clients.sh'

# Mirror docs/ to skills/atulya-docs/references/
bash scripts/generate-docs-skill.sh

# Start the API + control plane locally on default ports
./scripts/dev/start.sh

# Hindsight reference audit (must return empty)
grep -ric 'hindsight' --include='*.{py,ts,tsx,rs,go,md,json,yaml,yml,sh}' \
  /home/atulya-agent/atulya-agent/atulya 2>/dev/null | grep -v ':0$'
```

## Where to find existing precedents

When in doubt, copy the pattern from an analogous existing feature:

| Want to add … | Look at how this was done |
| --- | --- |
| A new configurable bank field | `max_observations_per_scope` (recent port) |
| A new compound boolean filter | `tag_groups` (recent port) — see `engine/search/tags.py` |
| An update mode for retain | `update_mode='append'` (recent port) — see `memory_engine` + `fact_storage.get_document_content` |
| A new MCP tool | Existing tools in the MCP layer; register them and add a test |
| A new docs page | Mirror an existing `atulya-docs/docs/developer/api/*.mdx` |
| A new control-plane view | Mirror an existing `atulya-control-plane/src/components/*-view.tsx` |
| A new test fixture | `atulya-api/tests/conftest.py` — see `memory`, `request_context` |
