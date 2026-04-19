---
name: git-commit
description: Design a meaningful git commit for the Atulya repo end-to-end — what commands to run to inspect the change, how to decide if it's one commit or several, how to write a message in this repo's `[type] ~ subject` convention with a structured body grouped by surface, and the exact `git add` / heredoc `git commit` invocations to use. Use whenever the user says "commit this", "git commit", "draft a commit message", "what should the commit be", or you've just finished a feature/fix and want to propose a commit before they ask.
---

# Git Commit (for AI Agents)

A repeatable recipe for turning a finished change in the Atulya monorepo into a
single, well-shaped commit (or a clean stack of commits) with a message a human
can skim in 10 seconds and a teammate can audit in 60.

## Core rules (do not skip)

1. **Never `git commit` without explicit user instruction.** Draft the message,
   show it, and wait. The system safety prompt is strict on this.
2. **Read the diff before drafting.** No exceptions. The message is a summary
   of the actual change, not of your intent.
3. **Use a heredoc for the message.** `git commit -m "..."` mangles newlines
   and quotes; `git commit -m "$(cat <<'EOF' ... EOF)"` does not.
4. **Never `--amend` a pushed commit.** Never use `--no-verify`. Never edit
   `git config`. Never force-push without explicit go-ahead.
5. **Group by surface, not by file.** A reader cares about *"the API gained X,
   the clients regenerated, docs updated"* — not about 47 file paths.
6. **One logical change per commit.** If you need the word "and" twice in the
   subject line, you probably need two commits.

## The 6-step recipe

### 1. Inspect — three commands, in parallel

```bash
git status --short
git diff --stat                     # for unstaged
git diff --cached --stat            # for already-staged
git log --oneline -10               # learn this repo's voice
```

If the change is large, also run:

```bash
git diff --stat | awk '{print $1}' | sort | uniq -c | sort -rn | head
```

to see which directories dominate the diff. That distribution is what your
commit body will be organized around.

### 2. Classify — pick exactly one type tag

Atulya uses bracketed type tags as the first token of the subject. Match the
existing voice (`git log --oneline -30` will show you):

| Tag | When |
| --- | --- |
| `[feature]` | New user-visible capability or new API surface |
| `[fix]` | Behavior was wrong and is now correct |
| `[bug]` | Same as `[fix]`, used interchangeably in this repo |
| `[improvement]` | Existing behavior preserved, made better (perf, UX, code) |
| `[refactor]` | No behavior change, internal reshape |
| `[docs]` | Docs/skills only |
| `[chore]` | Build, deps, ignore files, config |
| `[major]` | Cross-cutting introduction of a new subsystem |

If the change spans types (e.g. a feature that includes a fix), pick the
**dominant** tag and call out the secondary work in the body. If it spans
*equally*, that is the signal to split the commit (see step 6).

### 3. Decide — one commit or several?

Default to **one commit per logical change**. Split when *all* of these are
true:

- The pieces are independently revertable without breaking `main`.
- A reviewer would want to read them in order, not as a single diff.
- The user has time to review N PRs/commits, not 1.

Concretely for Atulya, these usually want their own commit:

- A regenerated client artifact bundle (`atulya-clients/**`) when paired with
  a non-trivial spec change — keep server change + regen together, but
  separate from unrelated fixes.
- Documentation-only sweeps that touch many `.md`/`.mdx` files.
- Toolchain/script bring-up (`scripts/`, `skills/release-management/`) that
  is logically separate from product code.

If unsure, draft **one commit** and offer a split as an option. Don't split
unilaterally.

### 4. Draft the subject line

Format:

```
[<type>] ~ <imperative subject, lowercase, no trailing period>
```

Constraints:

- ≤ 72 characters total.
- Imperative mood: *"add"*, *"fix"*, *"port"*, *"regenerate"* — not *"added"*,
  *"fixes"*.
- Concrete nouns over adjectives: *"retain-append + tag_groups +
  observation_cap"* beats *"three new features"*.
- If the commit closes a PR, append ` (#NN)` — match what `git log` shows.

Good (real, from `git log`):

- `[feature] ~ retain-append + tag_groups + observation_cap, end-to-end Linux toolchain`
- `[fix] ~ Update API request headers and enhance error handling`
- `[improvement] ~ node and helper in link`
- `[bug] ~ serialization fix`

Bad:

- `Update files` — what changed? why?
- `[feature] Added a new endpoint and fixed a bug and regenerated clients` — three commits in a trenchcoat.
- `WIP` — never commit WIP without `--fixup` or a `wip/` branch convention.

### 5. Draft the body — grouped by surface

Leave a blank line after the subject, then a one-paragraph **lede** (2–3
sentences: *what changed and why*), then `##`-style sections grouped by
surface. Wrap at ~78 columns.

For Atulya the surfaces are stable; reuse these section headers in this order
when present:

1. **Features** / **Behavior** — the user-visible change
2. **Clients & CLI** — what regenerated, what was hand-patched
3. **Control plane** — UI changes
4. **Toolchain & scripts** — `scripts/`, `skills/release-management/`
5. **Tests** — new files, updated assertions, why
6. **Docs & agent skills** — `atulya-docs/`, `skills/`
7. **Verification** — the green-build evidence (commands you actually ran)

Each bullet should answer *what + why*. "Refactored X" is weak; "Refactored
X to fix Y" is a commit message.

End the body with a **Verification** block listing the commands you ran and
that returned green. This is the part future-you will thank present-you for.

### 6. Commit — exact invocation

Stage intentionally — never blindly `git add .` unless `git status` is
already clean of unrelated noise:

```bash
git add <paths>          # explicit paths, or:
git add -u               # stage modifications + deletions of tracked files
git status --short       # confirm what is staged
```

Then commit with a heredoc so newlines and quotes survive:

```bash
git commit -m "$(cat <<'EOF'
[feature] ~ <subject>

<lede paragraph>

Features
- ...

Clients & CLI
- ...

Verification
- ./scripts/hooks/lint.sh clean
- atulya-api pytest -p no:xdist passes
EOF
)"
```

Verify the commit landed:

```bash
git log -1 --format='%H%n%s%n%n%b'
git status --short
```

If a pre-commit hook **modified** files (formatter, linter), re-stage them
and `--amend` *only that commit you just created in this session* — never
amend a commit that's already been pushed or that wasn't yours.

If a pre-commit hook **failed**, fix the underlying issue and create a *new*
commit. Do not `--amend` a failed/rejected commit.

## Worked example — the commit from this session

This is `01a3530` in `git log`, generated by exactly this recipe:

Subject:

```
[feature] ~ retain-append + tag_groups + observation_cap, end-to-end Linux toolchain
```

Why this subject works:

- One `[feature]` tag — the dominant intent.
- Three concrete nouns name *what* shipped.
- The `, end-to-end Linux toolchain` suffix flags the secondary toolchain
  work without inflating to a second commit.
- 91 chars — slightly over 72, accepted because the three feature names are
  load-bearing. Aim for 72; don't truncate meaning to hit it.

Body skeleton (full text in `git show 01a3530`):

```
<lede: ports three production features at full parity, zero residual hindsight>

Features
- Retain update_mode='append': ...
- tag_groups: ...
- max_observations_per_scope: ...

Clients & CLI
- Regenerated python, typescript, rust, go ...
- TypeScript: hand-maintained TagGroup union ...
- Rust: progenitor regen + cargo check clean
- Go: in-script patch for missing `os` import re-applied

Control plane
- bank-config-view.tsx exposes max_observations_per_scope
- Fixed pre-existing recharts v3 typing ...

Toolchain & scripts (Linux bring-up)
- scripts/generate-clients.sh: portable mktemp, `--` separator
- skills/release-management/docker.md rewritten as 6-phase playbook

Tests
- New test_observation_cap.py covering ...
- New test_retain_append_mode.py covering ...
- Bumped two stale assertions in test_hierarchical_config.py (17 -> 26)

Docs & agent skills
- atulya-docs configuration.md + retain.mdx + recall.mdx
- New skills/atulya-system-testing/, skills/atulya-dev-flow/

Verification (all green on Linux/Ubuntu 24.04)
- ./scripts/hooks/lint.sh clean
- atulya-api pytest -p no:xdist passes for all touched suites
- ./scripts/generate-clients.sh exits 0 end-to-end
- cargo check on atulya-clients/rust and atulya-cli clean
- atulya-clients/typescript npm run build clean
- atulya-control-plane npx tsc --noEmit clean
```

## Anti-patterns

| Anti-pattern | Why it fails | Fix |
| --- | --- | --- |
| `git commit -am "stuff"` | Stages every modified file blindly; "stuff" is meaningless | Stage explicitly, write a real message |
| `git commit -m "line1\nline2"` | `\n` is literal in most shells; you get one weird line | Use the heredoc form |
| Subject `Refactor code for improved readability` | Repo has many of these; they teach future-you nothing | Name *what* was refactored and *why* |
| Mixing a feature, a fix, and a regen in one commit | Impossible to revert one piece | Split into 2–3 commits |
| Drafting before reading the diff | Message describes intent, not reality | `git diff --stat` first, always |
| Auto-running `git commit` after a successful task | Violates the session-safety contract | Draft the message, show it, wait |
| Force-pushing to fix a typo in a pushed commit | Rewrites public history | Make a `[fix]` follow-up commit instead |
| `--no-verify` to skip a failing hook | Hides real lint/test failures from review | Fix the hook failure, then commit |

## Quick reference card

```bash
# 1. Inspect
git status --short
git diff --stat
git diff --cached --stat
git log --oneline -10

# 2. Stage intentionally
git add <paths>          # or: git add -u
git status --short       # confirm

# 3. Commit (only after user says "commit it")
git commit -m "$(cat <<'EOF'
[<type>] ~ <subject>

<lede>

<surface-grouped sections>

Verification
- <commands you ran that returned 0>
EOF
)"

# 4. Verify
git log -1 --format='%H%n%s%n%n%b'
git status --short
```

## When the user wants something other than a single commit

| Ask | Do |
| --- | --- |
| "Commit this" | Draft message → wait → commit on confirmation |
| "Split this commit" | Use `git reset HEAD~1` to unstage, then re-stage in groups, one `git commit` per group |
| "Squash these" | Only if commits are unpushed; `git reset --soft HEAD~N && git commit` |
| "Amend the last commit" | Allowed only if (a) you authored it this session, (b) it's unpushed; otherwise refuse and propose a follow-up commit |
| "Revert" | `git revert <sha>` (creates a new commit) — never `git reset --hard` on shared history |
| "Open a PR" | Hand off to the standard PR flow; commit message becomes the PR body's first section |

## Companion skills

- For *what* to test before drafting the Verification block:
  `skills/atulya-system-testing/`.
- For *where* the change should land (which surfaces): `skills/atulya-dev-flow/`.
- For PR-merge-readiness over time: `skills/babysit/` (Cursor-global skill).
