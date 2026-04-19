---
name: atulya-dev-flow
description: Disciplined development workflow for AI coding agents working in the Atulya monorepo — covers context gathering, branch hygiene, edit/lint/test cycle, API surface changes that require client regen, parallel vs sequential tool use, and the report-back template. Use at the start of any non-trivial Atulya coding task, or when the user asks how to "implement X", "port Y", "change the API", or "ship a feature" in this repo.
---

# Atulya Dev Flow (for AI Agents)

A repeatable, low-token workflow for landing changes in the Atulya monorepo
without burning the user's time on rework. Optimised for an agent like Claude
or GPT operating in Cursor.

## Core mindset

1. **Read before write.** Every file edit costs the user roundtrip; every
   incorrect edit costs them more. Spend tool calls on `Read`, `Grep`,
   `Glob`, `SemanticSearch` first.
2. **Sequential tools when dependent, parallel when independent.** Never
   serialise independent reads; never parallelise edits to the same file.
3. **Edit, don't recreate.** `StrReplace` over `Write`. Never use
   `cat`/`echo`/heredoc to "create" or "modify" a file — those are
   communication anti-patterns.
4. **The repo is the source of truth.** When in doubt, `Grep` the codebase
   for an existing precedent and follow it.
5. **One feature = all surfaces.** Atulya has five surfaces (Python API,
   Rust client+CLI, TS client, Go client, control-plane UI). A "feature" is
   not done until every relevant surface reflects it.

## Surface map

| Path | Owns | When you'll touch it |
| --- | --- | --- |
| `atulya-api/atulya_api/` | Server logic, Pydantic models, SQL, consolidation | Most feature work starts here |
| `atulya-api/atulya_api/api/http.py` | FastAPI route definitions | New endpoint or request/response field |
| `atulya-api/atulya_api/config.py` | `AtulyaConfig`, env loading, configurable/static/credential field categories | New configurable knob |
| `atulya-api/tests/` | pytest suite | Always — new logic needs new tests |
| `atulya-clients/{python,typescript,rust,go}/` | Generated clients | After API change → regen |
| `atulya-cli/` | Rust CLI consuming the Rust client | After API change → cargo check |
| `atulya-control-plane/src/` | Next.js UI | New configurable field → new form input |
| `atulya-docs/docs/` | User-facing docs | Every shipped feature needs a doc entry |
| `skills/atulya-docs/references/` | Agent-skill mirror of docs | Run `bash scripts/generate-docs-skill.sh` to refresh |
| `scripts/` | Build/release/regen scripts | Rarely — only to fix script bugs |

## The standard cycle

Copy this checklist at the start of any non-trivial task:

```
- [ ] 1. Understand the change
- [ ] 2. Plan (TodoWrite if 3+ steps)
- [ ] 3. Edit (StrReplace, follow code-intel standards)
- [ ] 4. Run targeted tests sequentially
- [ ] 5. Lint touched files
- [ ] 6. If API surface changed: regenerate clients
- [ ] 7. If clients regenerated: rebuild dependents (cargo, tsc)
- [ ] 8. Update docs (atulya-docs + skills/atulya-docs)
- [ ] 9. Hindsight reference audit
- [ ] 10. Report findings + propose commit message (do not commit unsolicited)
```

### 1. Understand the change

Before any edit, gather context:

- **`SemanticSearch`** for "how does X work?" / "where is Y handled?"
  questions when you don't know the file layout.
- **`Grep`** for exact symbol names, error messages, or known field names.
- **`Glob`** to find files by pattern (e.g. `**/test_*.py`).
- **`Read`** to load the actual file once you know the path.

Batch independent searches in **one** message. Example:

```
Parallel batch:
- Grep("max_observations_per_scope", path="atulya-api/")
- Grep("max_observations_per_scope", path="atulya-control-plane/src/")
- Read(/abs/path/to/relevant_file.py)
```

### 2. Plan

For tasks with 3+ logical steps, call `TodoWrite` with the step list and
mark the first one `in_progress` in the same tool batch as your first
substantive action. Update statuses as you progress. Never end your turn
with `in_progress` items.

For trivial 1–2 step tasks, skip TodoWrite — it's noise.

### 3. Edit

- **Always `Read` a file before editing it** (the platform requires this).
- **`StrReplace`** for any change to an existing file. Use enough surrounding
  context that `old_string` is unique. If it isn't unique, expand the
  context — don't rely on `replace_all` unless you genuinely want every
  occurrence changed.
- **`Write`** only for new files that don't exist yet.
- **`Delete`** to remove a file (don't blank it).
- **Never** use shell commands (`sed`, `awk`, `cat > file`, `echo >>`) to
  modify files. Even when the target is a config file or a markdown doc.

### 4. Run targeted tests sequentially

After editing a file, run the most specific test that exercises it:

```bash
# Single test, full traceback, stop on first fail
( cd atulya-api && uv run pytest -p no:xdist --timeout=180 \
  tests/test_<file>.py::test_<name> -xv )
```

`-p no:xdist` is **non-negotiable** for LLM-backed integration tests — see
[atulya-system-testing](../atulya-system-testing/SKILL.md#2-python-pytest--always-sequential).

Escalate to the whole file, then the whole suite, only after the targeted
test passes.

### 5. Lint touched files

```bash
./scripts/hooks/lint.sh
```

Runs ruff + ty (Python) and ESLint + Prettier (TS) in parallel across the
whole repo. Fast (≤30 s). Fix what you broke; **do not** silently fix
pre-existing lint that wasn't yours.

### 6. If API surface changed: regenerate

A change is an "API surface change" if it touches **any** of:

- `atulya-api/atulya_api/api/http.py` (routes, request/response shapes)
- `atulya-api/atulya_api/models/` (Pydantic API models)
- `atulya-api/atulya_api/config.py` field categories (configurable list)
- Anything that flows into the generated OpenAPI spec

If yes:

```bash
sg docker -c '. ~/.cargo/env && bash scripts/generate-clients.sh'
```

`sg docker` runs the command with the `docker` group active (see
[release-management/docker.md](../release-management/docker.md) for why).

The script runs Rust → Python → TS → Go in order and includes an in-script
`cargo check -p atulya-cli` as a contract test.

### 7. Rebuild dependents

After regen, **always** re-verify the four downstream consumers — the
generators occasionally produce shapes the consumers can't handle:

```bash
( cd atulya-clients/typescript && npm run build )
( cd atulya-control-plane      && npx tsc --noEmit )
( . ~/.cargo/env && cd atulya-cli && cargo check )
```

Common post-regen fixups are catalogued in
[atulya-system-testing/reference.md](../atulya-system-testing/reference.md#post-regen-drift).
The standard ones:

- TS: re-export a stable `TagGroup` union alias in `src/index.ts` (the
  generator inlines it per-property).
- Rust: re-apply the recursive `Box<TagGroup>` enum in `types.rs` if
  progenitor overwrote it.

### 8. Update docs

Every user-visible change needs **both**:

```bash
# Edit human-facing docs:
atulya-docs/docs/<area>/<page>.{md,mdx}

# Then mirror to the agent skill copy:
bash scripts/generate-docs-skill.sh
```

Skipping the skill copy means future agents (including you, next session)
won't see the documentation. The mirror script is fast (< 1 s) and
idempotent.

### 9. Hindsight reference audit

```bash
grep -ric 'hindsight' --include='*.{py,ts,tsx,rs,go,md,json,yaml,yml,sh}' \
  /home/atulya-agent/atulya-agent/atulya 2>/dev/null | grep -v ':0$'
```

Must return empty. If you ported logic from `hindsight`, scrub every
reference (paths, comments, docstrings, error messages).

### 10. Report

End every substantive turn with a structured summary:

```
## Summary

### What changed
- <surface>: <bullet description>

### Verification
| Gate | Result |
| ---- | ------ |
| Targeted pytest | ✅ N tests, M passed |
| Lint | ✅ |
| Cargo check | ✅ |
| TS build | ✅ |
| Control-plane tsc | ✅ |

### Files modified
- atulya-api/.../foo.py
- atulya-clients/typescript/src/index.ts

### Suggested commit message
"<type>(<scope>): <subject>"
```

**Do not run `git commit` unless the user asks for it.** The
"creating commits" rules in the system prompt are strict — wait for the
explicit instruction.

## Code standards (delegated)

Don't restate them here — read [code-intel/SKILL.md](../code-intel/SKILL.md)
for the binding standards (no raw `dict`, no multi-item tuple returns,
Pydantic boundary parsing, type hints required, comments explain "why" not
"what", etc.). They are enforced at review time.

## Tool-use cheat sheet

| Need to … | Use | Don't use |
| --- | --- | --- |
| Find a class definition | `Grep` for `class FooBar` | `SemanticSearch` |
| Find files by name pattern | `Glob` | `find` via `Shell` |
| Find files by content | `Grep` | `rg`/`grep` via `Shell` |
| Understand a flow you don't know | `SemanticSearch` | reading files at random |
| Read a known file | `Read` | `cat`/`head`/`tail` via `Shell` |
| Edit existing file | `StrReplace` | `sed`/`awk`/`Write` |
| Create new file | `Write` | `cat > file`/`echo >` |
| Delete file | `Delete` | `rm` via `Shell` |
| Run tests/builds | `Shell` | (no alternative) |
| Track multi-step work | `TodoWrite` | freeform prose |
| Check for lint issues post-edit | `ReadLints` | re-running the linter |

### Parallelism rules

**Parallel-safe** (batch in one message):
- Multiple `Read`s of different files
- Multiple `Grep`/`Glob` queries
- Multiple `Shell` commands with no shared state
- `Read` + `Grep` + `SemanticSearch` exploring the same area

**Must be sequential**:
- Edit → re-`Read` (to verify)
- `Write` → `Shell` (to test the new file)
- `git add` → `git commit` → `git push`
- Anything where the second tool consumes the first's output

## Common pitfalls (and the fix)

| Pitfall | Why it fails | Fix |
| --- | --- | --- |
| Running pytest in parallel against a local LLM | xdist + 20 s/call → mass timeouts | Always `-p no:xdist` |
| Editing a generated file (e.g. `types.gen.ts`) | Regen wipes it next run | Edit the source spec or the wrapper (`src/index.ts`) |
| Modifying a hand-maintained file inside a generated dir without a comment | Confuses next regen | Add a comment block explaining "this file is hand-maintained, generators must skip" |
| Adding a configurable field to `AtulyaConfig` without env loader / list / UI | UI lets users set it but the server ignores it | Touch all four: `config.py` (field + env + list), `bank-config-view.tsx` (UI), `configuration.md` (doc), `_validate_fields()` (range check) |
| Running `git commit` proactively | User wanted to review first | Wait for explicit instruction |
| Bumping a stale test assertion to make CI green without telling the user | Silent test rot accumulates | Update + flag it in the report |
| `sed -i` to "fix" a file | Bypasses StrReplace's safety net | Use StrReplace |
| `cat <<EOF > file` to create a file | Treats Shell as a file editor | Use Write |
| Skipping `bash scripts/generate-docs-skill.sh` after editing `atulya-docs/` | Future agents miss the doc | Always mirror |

## When something is unclear

- **Ambiguous spec** → ask the user **once**, then proceed with your best
  reading. Don't ask 5 clarifying questions in a row.
- **Stuck on a failure** → switch from "implement" to "investigate": read
  the failing test, read the function under test, read the most recent commit
  to that file (or `Grep` for related changes).
- **Found a script bug while doing unrelated work** → fix it, mention it in
  the report, but don't expand scope into a full audit.

## When the work is done

- ✅ Targeted pytest passes
- ✅ Lint passes for files you touched
- ✅ If API changed: client regen + dependent rebuilds pass
- ✅ Docs updated in both `atulya-docs/docs/` and `skills/atulya-docs/references/`
- ✅ Hindsight grep returns zero
- ✅ Final report posted

For the heavyweight "ship-it" pre-commit / pre-PR validation, hand off to
[atulya-system-testing](../atulya-system-testing/SKILL.md).

## Deep reference

For task-specific playbooks (porting a feature from another repo, adding a
new endpoint end-to-end, adding a configurable bank setting, etc.) see
[playbook.md](playbook.md).
