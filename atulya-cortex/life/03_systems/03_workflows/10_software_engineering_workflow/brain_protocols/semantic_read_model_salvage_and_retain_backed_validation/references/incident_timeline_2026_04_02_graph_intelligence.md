# Incident Timeline: 2026-04-02 Graph Intelligence Semantic Salvage

This timeline records the important events and commands from the graph-intelligence rewrite incident so the reasoning chain is replayable later.

## Trigger

Visible concern:

- a long semantic rewrite had landed in `graph_intelligence.py`
- the user needed a serious review before bad logic reached production
- there was concern that the existing tests might be too synthetic and not representative of real embeddings or real retain flows

## Phase 1: Contract Review

Command:

```bash
cd /Users/anuragatulya/github/atulya/atulya-api
uv run pytest tests/test_graph_intelligence.py -q
```

Observed event:

- the targeted subsystem file failed broadly, not just in one corner case
- failures covered contradiction surfacing, missing-embedding fallback, stale behavior, investigation output, and endpoint behavior

Impact:

- this established that the rewrite was not safe to publish as-is

## Phase 2: Rewrite Intent Assessment

Events:

- the rewrite was trying to fix real issues such as ownership routing, same-document false positives, paraphrase churn, and semantic contradiction sensitivity
- the best idea in the patch was subject ownership via a leading-entity rule
- the dangerous parts were cluster-driven short-circuiting, hard embedding dependence, and non-unique event IDs

Impact:

- the path forward became salvage, not blanket revert and not blanket acceptance

## Phase 3: Production-Ready Plan

Events:

- restore the known behavioral contract first
- keep ownership and same-document guards
- add deterministic tests for the exact logic regressions
- add a tiny retain-driven real corpus using the local embedding system

Impact:

- the implementation target became "smarter but provable" rather than "more semantic at any cost"

## Phase 4: Logic Rebuild And Coverage Expansion

Commands used during the verification loop:

```bash
cd /Users/anuragatulya/github/atulya/atulya-api
uv run ruff check atulya_api/engine/graph_intelligence.py tests/test_graph_intelligence.py tests/graph_intelligence_eval_helper.py
uv run pytest tests/test_graph_intelligence.py -q
```

Observed events:

- graph intelligence was rebuilt around contract-safe semantics
- a tiny helper corpus was added for contradiction, state change, duplicate fact, and ownership trap scenarios
- the final subsystem file passed with `27 passed`

Impact:

- the semantic improvements were now backed by both exact logic tests and a real retain path

## Phase 5: Publish Scope Mapping

Commands:

```bash
cd /Users/anuragatulya/github/atulya
git status --short
git diff --stat -- \
  atulya-api/atulya_api/config.py \
  atulya-api/atulya_api/engine/graph_intelligence.py \
  atulya-api/atulya_api/engine/memory_engine.py \
  atulya-api/tests/test_graph_intelligence.py \
  atulya-api/tests/graph_intelligence_eval_helper.py \
  atulya-cortex/life/40_knowledge/17_lessons_learned/2026-04-02_graph_intelligence_semantic_rewrites_need_contract_tests_and_real_retain_corpus.md
git branch --show-current
git diff -- atulya-api/atulya_api/engine/memory_engine.py
```

Observed events:

- the branch was `main`
- `memory_engine.py` needed to stay in scope because `chunk_id` made the same-document guard work end-to-end
- the lesson note was added to the Cortex knowledge shelf before publish

## Phase 6: First Commit

Commands:

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

Observed events:

- repo pre-commit hooks ran `scripts/hooks/lint.sh`
- lint passed
- commit `efaae34` was created

## Phase 7: Post-Commit Dirty Tree Investigation

Commands:

```bash
git status --short
git diff -- atulya-api/atulya_api/engine/graph_intelligence.py
rg -n "lint.sh|ruff format|ruff check --fix|pre-commit" -S .git/hooks scripts .github atulya-api
sed -n '1,140p' scripts/hooks/lint.sh
cd /Users/anuragatulya/github/atulya/atulya-api
uv run ruff check atulya_api/engine/graph_intelligence.py
uv run ruff format --check atulya_api/engine/graph_intelligence.py
```

Observed events:

- `graph_intelligence.py` remained modified after the commit
- the diff was formatting-only
- the hook script was mutating files with `uv run ruff format .` after Git had already constructed the commit snapshot
- the hook did not restage changed files

Impact:

- this explained the apparently confusing "successful commit but dirty tree" state

## Phase 8: Formatter Cleanup Commit

Commands:

```bash
cd /Users/anuragatulya/github/atulya
git add atulya-api/atulya_api/engine/graph_intelligence.py
git commit -m "Apply graph intelligence formatter cleanup"
git status --short
git log --oneline -2
```

Observed events:

- hooks passed again
- formatter-only commit `6fcf797` was created
- `main` became clean

## Final State

Operational result:

- semantic graph logic was hardened without changing the public API
- tests covered exact invariants, local real embeddings, and a tiny retain-driven corpus
- the publish history stayed meaningful:
  - `efaae34` `Harden graph intelligence semantics with real retain checks`
  - `6fcf797` `Apply graph intelligence formatter cleanup`

## Lasting Learning

- one compelling real example is not enough proof for a semantic subsystem rewrite
- deterministic tests and a tiny real retain corpus should both agree before publish
- mutating hooks can create legitimate post-commit diffs, so publish hygiene needs its own diagnostic pattern
