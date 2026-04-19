---
name: atulya-system-testing
description: Run the Atulya repo through end-to-end system testing — toolchain check, lint, Python pytest, Rust cargo check, TypeScript build, control-plane typecheck, OpenAPI + client regen as a contract test, cross-client field smoke test, and hindsight-leak audit. Use when validating a change before commit/PR, after pulling main, before a release, or when the user asks to "run all tests", "verify everything", "system sanity check", or "end-to-end test".
---

# Atulya System Testing

Drive the Atulya monorepo through a full-system green build deterministically.
Every gate has a known failure mode, a known fix, and a sequential rerun
strategy that survives the slow local LLM at `ATULYA_API_BASE_URL`.

## Mental model

The repo has **five testable surfaces**, each with its own toolchain:

| Surface | What's tested | Tool | Why it can break |
| --- | --- | --- | --- |
| Python API | `atulya-api`, `atulya-dev`, `atulya-embed` | `uv run pytest`, `ruff`, `ty` | Logic, schema, async, LLM contracts |
| Rust CLI + client | `atulya-cli`, `atulya-clients/rust` | `cargo check`, `cargo build` | Generated client drift, recursive types |
| TypeScript client | `atulya-clients/typescript` | `tsc` | Inlined `oneOf` types, missing exports |
| Control-plane UI | `atulya-control-plane` (Next.js) | `npx tsc --noEmit`, `next build` | Recharts typings, generated-types shape |
| OpenAPI contract | `atulya-docs/static/openapi.json` + four clients | `scripts/generate-clients.sh` | Spec drift, codegen toolchain bugs |

**Rule**: never declare success on a single surface. Run all five, in the
order below.

## Required toolchain (verify before anything else)

```bash
docker --version          # ≥ 24.x, daemon reachable: `docker info` works without sudo
uv --version              # any recent
node --version            # ≥ 20.9 (project requires v22 LTS)
cargo --version           # via rustup, under $HOME/.cargo
go version                # ≥ 1.22 (Ubuntu 24.04 ships 1.22.2)
```

If `docker info` fails with "permission denied", the user's shell hasn't
picked up the `docker` group yet. Use `sg docker -c '<cmd>'` to run docker
commands in a one-shot subshell, or have them `newgrp docker` / re-login.
Full install playbook: [release-management/docker.md](../release-management/docker.md).

## End-to-end test flow

Copy this checklist and tick items as you go:

```
- [ ] 0. Toolchain check
- [ ] 1. Lint (./scripts/hooks/lint.sh)
- [ ] 2. Python pytest (sequential, --timeout=180)
- [ ] 3. Cargo check (atulya-cli + atulya-clients/rust)
- [ ] 4. TypeScript client build
- [ ] 5. Control-plane tsc --noEmit
- [ ] 6. OpenAPI + client regen (scripts/generate-clients.sh)
- [ ] 7. Post-regen rebuild of dependents (cargo, tsc)
- [ ] 8. Cross-client field smoke test
- [ ] 9. Hindsight reference audit
- [ ] 10. Report findings to user
```

Run from the repo root: `/home/atulya-agent/atulya-agent/atulya`.

### 0. Toolchain check

```bash
which docker cargo go node uv
docker info | head -3            # must succeed without sudo
. ~/.cargo/env 2>/dev/null || true
```

If anything is missing, **stop** and direct the user to the install playbook
in [release-management/docker.md](../release-management/docker.md). Do not try
to install toolchains yourself — `sudo` requires their password.

### 1. Lint

```bash
./scripts/hooks/lint.sh
```

This runs ESLint, Prettier, Ruff (check + format), and `ty` across `atulya-api`,
`atulya-dev`, `atulya-embed`, and `atulya-control-plane` in parallel. The
script is fast (≤ 30 s on this repo). On failure, **report — do not fix
silently** unless you introduced the violation.

### 2. Python pytest — ALWAYS sequential

```bash
cd atulya-api
uv run pytest -p no:xdist --timeout=180
cd ..
```

**This is the most common foot-gun.** `pyproject.toml` configures pytest-xdist
parallelism by default. The local LLM at `ATULYA_LLM_BASE_URL` (LM Studio /
Ollama in `.env`) takes 10–35 s per consolidation call, so under xdist
contention the per-test timeout fires and you get phantom "FAILED" reports.

When the parallel run shows ≥ 50 failures, **do not believe them**. Re-run
sequentially. Failures that disappear are infrastructure flake; failures that
persist are real regressions worth investigating.

For a fast feedback loop while iterating, run a single file:

```bash
( cd atulya-api && uv run pytest -p no:xdist --timeout=180 \
  tests/test_observation_cap.py -v )
```

For pre-PR confidence, run the **full** suite without xdist (it takes ~30 min
against a local LLM; budget accordingly).

### 3. Cargo check

```bash
. ~/.cargo/env
( cd atulya-clients/rust && cargo check )
( cd atulya-cli         && cargo check )
```

The CLI depends on the Rust client; if the client compiles but the CLI
doesn't, the regenerated client surface drifted from what the CLI consumes.
Common cause: a hand-maintained type (e.g. recursive `TagGroup` enum) was
overwritten by `progenitor` during regen.

### 4. TypeScript client build

```bash
( cd atulya-clients/typescript && npm run build )
```

Pure `tsc`, fast. If it fails with "has no exported member named X", the
generator likely inlined a `oneOf` union per property instead of emitting a
named alias. Add the alias as a hand-maintained re-export in `src/index.ts`
(see existing `TagGroup` precedent).

### 5. Control-plane typecheck

```bash
( cd atulya-control-plane && npx tsc --noEmit )
```

There is no `typecheck` npm script — invoke `tsc` directly. The control plane
consumes the generated TypeScript client, so this catches downstream breakage
from step 4 even when step 4 itself passes.

### 6. OpenAPI + client regen (contract test)

```bash
sg docker -c '. ~/.cargo/env && bash scripts/generate-clients.sh'
```

`sg docker -c '...'` runs the command inside a subshell that has the `docker`
group active — necessary if the agent shell hasn't picked up group membership
yet. The script:

1. Checks the OpenAPI Generator backend (Docker preferred, local
   `openapi-generator-cli` fallback).
2. Sanitizes the spec via `scripts/sanitize-openapi-for-clients.py`.
3. Regenerates Rust → Python → TypeScript → Go in that order.
4. Re-runs `cargo check -p atulya-cli` against the regenerated Rust client as
   an in-script contract test.

A successful run ends with:

```
✅ Client generation complete!
```

Common script-level failures are catalogued in
[reference.md](reference.md#known-script-bugs).

### 7. Post-regen rebuild

After regen, rebuild every dependent surface to catch drift:

```bash
. ~/.cargo/env
( cd atulya-clients/rust   && cargo check )
( cd atulya-cli            && cargo check )
( cd atulya-clients/typescript && npm run build )
( cd atulya-control-plane  && npx tsc --noEmit )
```

If any of these fail **only after regen**, the generated output changed
shape. See [reference.md](reference.md#post-regen-drift) for the standard
fixups (e.g. re-exporting a stable `TagGroup` alias in the TS client).

### 8. Cross-client field smoke test

Confirms a feature actually landed in every surface, not just one. Each path
must return a non-zero count for fields you expect to be present.

```bash
for f in \
  atulya-docs/static/openapi.json \
  atulya-clients/python/atulya_client_api/models/memory_item.py \
  atulya-clients/typescript/generated/types.gen.ts \
  atulya-clients/go/model_recall_request.go \
  atulya-clients/rust/src/lib.rs; do
  count=$(grep -c '<field1>\|<field2>\|<field3>' "$f" 2>/dev/null) \
    && printf "  %4s  %s\n" "$count" "$f" \
    || printf "  MISS  %s\n" "$f"
done
```

A `0` or `MISS` on any line means that surface didn't pick up the new field —
either the regen didn't run, the spec doesn't expose the field, or a manual
hand-patch is needed in that client.

### 9. Hindsight reference audit

Atulya was forked from `hindsight`. There must be **zero** mentions of
`hindsight` anywhere in the source tree.

```bash
grep -ric 'hindsight' --include='*.{py,ts,tsx,rs,go,md,json,yaml,yml,sh}' \
  /home/atulya-agent/atulya-agent/atulya 2>/dev/null \
  | grep -v ':0$'
# (empty output above = clean)
```

If anything matches, fix it before declaring success.

### 10. Report

Always end with a single, structured status table the user can scan in 5 s.
Template:

```
| Gate | Result |
| ---- | ------ |
| Toolchain | ✅ docker 29.x / cargo 1.95 / go 1.22 / node 22 |
| Lint | ✅ all parallel jobs pass |
| Python pytest | ✅ N passed, M skipped |
| Cargo check (rust client + cli) | ✅ |
| TypeScript client build | ✅ |
| Control-plane tsc --noEmit | ✅ |
| Client regen (contract) | ✅ all 4 clients regenerated |
| Cross-client smoke test | ✅ <field> in all 5 surfaces |
| Hindsight audit | ✅ zero references |
```

If anything is amber/red, list the exact file + line, the failure mode, and
your proposed fix. Do not silently mutate test assertions to make a red gate
green — that's how regressions ship.

## Performance hints

- **Local LLM is the bottleneck.** Single consolidation call ≈ 10–35 s. Plan
  budgets accordingly: a 1000-test suite hits ~30 min sequential.
- **Cargo cache is incremental.** First `cargo check` is slow (1–2 min); subsequent
  ones are seconds.
- **Docker images are cached locally.** `openapitools/openapi-generator-cli:v7.10.0`
  is ~700 MB; pull once, reuse forever.
- **Use `sg docker -c '...'`** to avoid telling the user to re-login when
  driving docker from the agent shell.

## Common false alarms

| Symptom | Looks like | Actually | Fix |
| --- | --- | --- | --- |
| 100+ pytest failures | Massive regression | xdist + slow LLM timeout | Re-run with `-p no:xdist` |
| `❌ OpenAPI Generator backend unavailable` | Docker broken | Shell missing `docker` group | `sg docker -c '<cmd>'` or `newgrp docker` |
| `mktemp: too few X's in template` | Script bug | GNU vs BSD mktemp portability | Already fixed — template ends in `.XXXXXX` |
| `unknown shorthand flag: 'o' in -o` | openapi-generator broken | `-o` leaked to `docker run` | Already fixed — `--` separator in script |
| TS error: `has no exported member 'TagGroup'` | Client broken | Generator inlines unions | Hand-add named alias in `src/index.ts` |
| `Property 'label' does not exist on type 'TooltipProps'` | Recharts broken | v3 split tooltip types | Use `Partial<TooltipContentProps<...>>` |
| `len(configurable) == 17` test fails | Config regression | Stale assertion (we have 26) | Update assertion to match reality |

## Deep reference

For the full command matrix, per-script flags, and detailed troubleshooting,
read [reference.md](reference.md).
