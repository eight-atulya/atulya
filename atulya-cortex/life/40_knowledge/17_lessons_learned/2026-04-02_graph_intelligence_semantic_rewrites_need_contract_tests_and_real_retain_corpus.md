# Graph Intelligence Semantic Rewrites Need Contract Tests And A Tiny Real-Retain Corpus

Date: 2026-04-02
Repo: atulya
Area: graph intelligence, state detection, contradiction routing, semantic evaluation

## Trigger

Graph intelligence was rewritten to become more semantically aware: clustering paraphrases, widening contradiction similarity bounds, routing contradictions to the leading entity, and using document-level guards to suppress same-source noise.

The rewrite improved one targeted real-world case, but it also regressed core graph behavior that the control plane and API already depended on.

## Root Cause

The failure was not one bad threshold. It was a combination of three issues:

- the rewrite mixed several behavior changes into one patch
- targeted debugging focused on one ownership case, not the subsystem contract
- the test suite had strong contract coverage, but no tiny real-retain corpus to judge whether "smarter" logic actually helped end-to-end

Specific regressions included:

- contradiction scans being skipped when semantic clustering collapsed evidence into one state
- change detection depending too heavily on embeddings, which broke missing-embedding paths
- multi-event nodes emitting non-unique event IDs, which risked collapsing events downstream

## Better System Design

For semantic read-model rewrites:

1. preserve the existing subsystem contract first
2. reintroduce smarter heuristics one at a time
3. keep a deterministic logic lane for exact invariants
4. add a tiny retain-driven real corpus for end-to-end semantic checks
5. keep the real corpus small enough to run on local models without making the suite unusably slow

The key idea is that semantic improvements should be proven in two ways:

- exact unit tests that pin down logic
- a minimal real-system path that validates extraction, entities, embeddings, chunk/document handling, and graph surfacing together

## Applied Pattern

This graph-intelligence salvage used:

- subject ownership via leading-entity detection
- document-aware contradiction suppression using `chunk_id`
- semantic dedup for exact/near-identical restatements
- unique event IDs for multi-step timelines
- restored fallback behavior when embeddings are missing
- a tiny real-retain graph corpus plus a reusable evaluation helper

The shipped validation shape became:

- synthetic graph tests for exact change/contradiction/stale/ranking rules
- local-embedding tests for semantic realism
- one tiny retain-driven corpus for tricky ownership and duplicate cases

## Practical Rule

If a semantic rewrite fixes one high-value example but breaks the existing contract, treat it as a source of ideas, not as the implementation baseline.

Keep:

- the insight
- the focused heuristics
- the new tests

Do not keep:

- the whole rewrite shape
- widened thresholds
- or the new routing model

unless the contract suite and the tiny real corpus both agree.

## Validation Rule

For graph-intelligence changes:

- run targeted lint on the changed files
- run the full `tests/test_graph_intelligence.py` file
- make sure the deterministic logic lane passes
- make sure the real local-embedding lane passes
- make sure the retain-driven corpus passes without expanding into a large slow suite

Do not rely on one offline debug trace or one real example as proof that the subsystem is ready to publish.

## Expected Benefits

- smarter graph-intelligence improvements can ship without breaking existing UI/API behavior
- ownership fixes do not regress unrelated entities or duplicate handling
- future threshold tuning has a reusable semantic proof pack
- semantic evaluation stays realistic without making normal iteration unbearably slow

## Cortex Links

- Workflow protocol: [semantic_read_model_salvage_and_retain_backed_validation](../../03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/semantic_read_model_salvage_and_retain_backed_validation/BRAIN.md)
- Command trail: [incident_timeline_2026_04_02_graph_intelligence.md](../../03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/semantic_read_model_salvage_and_retain_backed_validation/references/incident_timeline_2026_04_02_graph_intelligence.md)
