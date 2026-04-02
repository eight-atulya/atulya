# Command Patterns

This reference supports the `semantic_read_model_salvage_and_retain_backed_validation` protocol.

The commands below combine reusable patterns with the exact command trail used during the 2026-04-02 graph-intelligence salvage.

## Reconstruct The Failing Contract

```bash
cd /Users/anuragatulya/github/atulya/atulya-api
uv run pytest tests/test_graph_intelligence.py -q
```

Use the targeted subsystem file first. A semantic incident is usually easier to reason about from one high-signal contract file than from the entire repo.

## Inspect The Publish Scope

```bash
cd /Users/anuragatulya/github/atulya
git status --short
git diff --stat -- \
  atulya-api/atulya_api/config.py \
  atulya-api/atulya_api/engine/graph_intelligence.py \
  atulya-api/atulya_api/engine/memory_engine.py \
  atulya-api/tests/test_graph_intelligence.py \
  atulya-api/tests/graph_intelligence_eval_helper.py
git branch --show-current
```

When the branch is `main`, be extra strict about staging only the semantic-fix scope.

## Verify The Exact Files That Matter

```bash
git diff -- atulya-api/atulya_api/engine/memory_engine.py
git diff -- \
  atulya-api/atulya_api/config.py \
  atulya-api/atulya_api/engine/graph_intelligence.py \
  atulya-api/tests/test_graph_intelligence.py
```

Use targeted diffs to separate required plumbing such as `chunk_id` from unrelated worktree noise.

## Validate The Rebuilt Subsystem

```bash
cd /Users/anuragatulya/github/atulya/atulya-api
uv run ruff check atulya_api/engine/graph_intelligence.py tests/test_graph_intelligence.py tests/graph_intelligence_eval_helper.py
uv run pytest tests/test_graph_intelligence.py -q
```

This validation shape is the minimum proof pack:

- exact logic lane
- local real-embedding lane
- tiny retain-driven lane

## Capture The Lesson In Cortex

```bash
cd /Users/anuragatulya/github/atulya
sed -n '1,220p' atulya-cortex/life/40_knowledge/17_lessons_learned/2026-04-02_graph_intelligence_semantic_rewrites_need_contract_tests_and_real_retain_corpus.md
```

The lesson shelf captures the distilled rule. The protocol references capture the operational trail.

## Stage And Commit The Scoped Publish Set

```bash
git add \
  atulya-api/atulya_api/config.py \
  atulya-api/atulya_api/engine/graph_intelligence.py \
  atulya-api/atulya_api/engine/memory_engine.py \
  atulya-api/tests/test_graph_intelligence.py \
  atulya-api/tests/graph_intelligence_eval_helper.py \
  atulya-cortex/life/40_knowledge/17_lessons_learned/2026-04-02_graph_intelligence_semantic_rewrites_need_contract_tests_and_real_retain_corpus.md
git commit -m "Harden graph intelligence semantics with real retain checks"
```

## Diagnose A Post-Commit Dirty Tree

If `git status --short` still shows a modified file after commit, check whether the hook mutates files:

```bash
git diff -- atulya-api/atulya_api/engine/graph_intelligence.py
rg -n "lint.sh|ruff format|ruff check --fix|pre-commit" -S .git/hooks scripts .github atulya-api
sed -n '1,140p' scripts/hooks/lint.sh
```

This is the key pattern from the incident:

- commit hooks ran `uv run ruff format .`
- Git had already built the commit snapshot
- the formatter rewrote the file afterward
- the hook did not restage the file

## Verify The Leftover Diff Is Formatting-Only

```bash
cd /Users/anuragatulya/github/atulya/atulya-api
uv run ruff check atulya_api/engine/graph_intelligence.py
uv run ruff format --check atulya_api/engine/graph_intelligence.py
```

If these pass and the diff is only layout / spacing, prefer a tiny formatter-only follow-up commit.

## Commit The Formatter Cleanup Safely

```bash
cd /Users/anuragatulya/github/atulya
git add atulya-api/atulya_api/engine/graph_intelligence.py
git commit -m "Apply graph intelligence formatter cleanup"
git status --short
git log --oneline -2
```

## Good Heuristics

- If a semantic rewrite is promising but unstable, salvage it instead of pushing the whole shape.
- Keep one test file as the canonical contract gate for the subsystem.
- Use a tiny retain-backed corpus instead of inventing a giant slow evaluation harness.
- If a hook mutates files, treat the extra diff as a publish-hygiene issue, not as proof the original logic is broken.
- Capture both the short lesson and the exact command trail so future incidents can replay the path quickly.
