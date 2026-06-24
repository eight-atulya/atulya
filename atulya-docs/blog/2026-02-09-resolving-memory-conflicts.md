---
title: How Atulya handles memory conflicts
description: Contradictory facts, temporal evolution, and audit trails in the consolidation pipeline.
authors: [atulya]
date: 2026-02-09
hide_table_of_contents: true
---

# How Atulya handles memory conflicts

Reality changes. A CRM agent learns "Acme Corp is a prospect" in January and "Acme Corp signed a contract" in March. Naive memory either drops history or keeps duplicate facts.

Atulya tracks **how knowledge evolves**, not just the latest string.

<!-- truncate -->

## Facts vs consolidated knowledge

**Facts** are immediate observations from a single retain. **Observations** are durable knowledge synthesized over time. Consolidation runs in the background after retain.

## Finding related observations

When a new fact arrives, `_find_related_observations` uses recall with:

- Semantic similarity (embeddings)
- Token budget via `consolidation_max_tokens`
- Strict tag matching (`tags_match="all_strict"`) to avoid cross-scope leakage

```python
recall_result = await memory_engine.recall_async(
    bank_id=bank_id,
    query=query,
    max_tokens=config.consolidation_max_tokens,
    fact_type=["observation"],
    tags=tags,
    tags_match="all_strict",
)
```

## LLM conflict analysis

`_consolidate_with_llm` compares the new fact to candidate observations in one call. Context includes observation text, proof counts, source memories, and a **chronological time series**.

## Three merge strategies

**Redundant:** Same meaning, different wording → refine one observation.

**Contradiction:** Opposite claims about the same topic → preserve both states with temporal markers. Updated text explains the arc; when unclear, recency wins.

**State update:** New information replaces old state → explicit transition language ("used to", "now", "changed from X to Y").

## Example: evolving B2B relationship

Facts over six months:

1. January: interest in enterprise tier
2. February: CTO integration meeting
3. April: $50K contract
4. September: upgrade to $150K after regional expansion

Naive storage: "Acme is on $150K."
Consolidated observation: prospect → $50K customer (April) → $150K tier (September) after expansion.

An agent can answer "How did we land Acme?" with the full arc.

## Temporal metadata

```sql
occurred_start = LEAST(occurred_start, COALESCE($7, occurred_start))
occurred_end = GREATEST(occurred_end, COALESCE($8, occurred_end))
mentioned_at = GREATEST(mentioned_at, COALESCE($9, mentioned_at))
```

- `occurred_start`: earliest time the state was true
- `occurred_end`: latest related event
- `mentioned_at`: last reference

## History audit trail

```python
history.append({
    "previous_text": model["text"],
    "changed_at": datetime.now(timezone.utc).isoformat(),
    "reason": reason,
    "source_memory_id": str(memory_id),
})
```

Agents can explain *why* knowledge changed and which fact triggered it.

## Tag boundaries

New observations inherit source fact tags. On update, tags union so contributors retain access. Consolidation never crosses strict tag scopes:

```python
existing_tags = set(model.get("tags", []) or [])
source_tags = set(source_fact_tags or [])
merged_tags = list(existing_tags | source_tags)
```

## Durable vs ephemeral

Consolidation targets lasting knowledge. "User is in Room 105 right now" is ephemeral; "Acme Corp is in Building B" is durable. That cuts false conflict noise.

## Why it matters

Contradictions do not require picking a single winner. Temporal narrative + history + scoped consolidation gives agents explainable, evolving understanding for preferences, relationships, and compliance-sensitive updates.
