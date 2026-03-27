---
title: Frequently Asked Questions
description: Common questions and answers about Atulya
hide_table_of_contents: false
---

# Frequently Asked Questions

### What is Atulya and how does it differ from RAG?

Atulya is an agent memory system that provides long-term memory for AI agents using biomimetic data structures. Unlike traditional RAG (Retrieval-Augmented Generation), Atulya:

- **Stores structured facts** instead of raw document chunks
- **Builds mental models** that consolidate knowledge over time
- **Uses graph-based relationships** between entities and concepts
- **Supports temporal reasoning** with time-aware retrieval
- **Enables disposition-aware reflection** for nuanced reasoning

For a detailed comparison, see [RAG vs Memory](/developer/rag-vs-atulya).

---

### Why use Atulya instead of other solutions?

Atulya is purpose-built for agent memory with unique advantages:

- **State-of-the-art accuracy**: Ranked #1 LongMemEval benchmarks for agent memory (see [details](https://benchmarks.atulya.eightengine.com/))
- **Built on proven technology**: PostgreSQL - battle-tested, reliable, and widely understood
- **Cloud-native architecture**: Designed for modern cloud deployments with horizontal scalability
- **Flexible deployment**: Self-host or use Atulya Cloud - works with any LLM provider
- **True long-term memory**: Builds mental models that consolidate knowledge over time, not just retrieval
- **Graph-based reasoning**: Understands relationships between entities and concepts for richer context
- **Production-ready**: Scales to millions of memories with 50-500ms recall latency
- **Developer-friendly**: Simple APIs (retain, recall, reflect), SDKs for Python/TypeScript/Go/Rust, integrations with LiteLLM/Vercel AI SDK

Unlike vector databases (just search) or RAG systems (document retrieval), Atulya provides **living memory** that evolves with your users.

---

### Which LLM providers are supported?

Atulya supports:
- **OpenAI**
- **Anthropic**
- **Google Gemini**
- **Groq**
- **Ollama** (local models)
- **LM Studio** (local models)
- **Any OpenAI-compatible provider** (Together AI, Fireworks, DeepInfra, etc.)
- **Any Anthropic-compatible provider**

**Using local models with Ollama:**
```bash
ATULYA_API_LLM_PROVIDER=ollama
ATULYA_API_LLM_MODEL=llama3.1
ATULYA_API_LLM_BASE_URL=http://localhost:11434
```

**Using local models with LM Studio:**
```bash
ATULYA_API_LLM_PROVIDER=lmstudio
ATULYA_API_LLM_MODEL=your-model-name
ATULYA_API_LLM_BASE_URL=http://localhost:1234/v1
```

Configure your provider using the `ATULYA_API_LLM_PROVIDER` environment variable. See [Configuration](/developer/configuration) and [Models](/developer/models) for details.

---

### Which model should I use with Atulya?

The **[Model Leaderboard](https://benchmarks.atulya.eightengine.com/)** benchmarks models across accuracy, speed, cost, and reliability for retain, reflect, and observation consolidation — it's the best place to find the right trade-off for your use case.

[![Model Leaderboard](/img/leaderboard.png)](https://benchmarks.atulya.eightengine.com/)

See [Models](/developer/models) for the full list of supported and tested models, provider defaults, and configuration examples.

---

### Do I need to host my own infrastructure?

No! You have two options:

1. **Atulya Cloud** - Fully managed service at [ui.atulya.eightengine.com](https://ui.atulya.eightengine.com)
2. **Self-hosted** - Deploy on your own infrastructure using Docker or direct installation

See [Installation](/developer/installation) for self-hosting instructions.

---

### What are the minimum system requirements for self-hosting?

For running the Atulya API server locally:
- Python 3.11+
- 4GB RAM minimum (8GB recommended for production)
- LLM API key (OpenAI, Anthropic, etc.) or local LLM setup

See [Installation](/developer/installation) for setup instructions.

---

### How do I isolate user data?

A **memory bank** is an isolated memory store (like a "brain") that contains its own memories, entities, relationships, and optional disposition traits (skepticism, literalism, empathy). Banks are completely isolated from each other with no data leakage.

There are two approaches for multi-user applications:

**1. Per-user memory banks** (recommended for most use cases)
- Create one bank per user (e.g., `bank_id="user-123"`)
- Easiest setup and strongest data isolation
- Perfect for per-user queries and personalization
- Each bank can have unique disposition traits and background context
- **Limitation**: Cannot perform cross-user analysis (e.g., "What is the most mentioned topic across all users?")

**2. Single bank with tags** (for applications needing aggregated insights)
- Use one bank for the entire application
- Tag memories with user identifiers during retain (e.g., `tags={"user_id": "user-123"}`)
- Filter by tags during recall/reflect for per-user queries
- **Advantage**: Enables both per-user AND cross-user queries (e.g., analyze specific users or aggregate across all users)

Choose per-user banks for simplicity and privacy, or single bank with tags if you need holistic reasoning across users. See [Memory Banks](/developer/api/memory-banks) for management details.

---

### What's the difference between retain, recall, and reflect?

Atulya has three core operations:

- **Retain**: Store data (facts, entities, relationships)
- **Recall**: Search and retrieve raw memory data based on a query
- **Reflect**: Use an AI agent to answer a query using retrieved memories

See [Operations](/developer/api/operations) for API details.

---

### When should I use recall vs reflect?

**Use recall when:**
- You want raw facts to feed into your own reasoning or prompt
- You need maximum control over how memories are interpreted
- You're doing simple fact lookup (e.g., "What did Alice say about X?")
- Latency is critical — recall is significantly faster (50-500ms vs 1-10s)
- You want to build your own answer synthesis layer on top of retrieved memories

**Use reflect when:**
- You want a ready-to-use answer generated from memories (no extra LLM call needed)
- You need disposition-aware responses shaped by the bank's personality traits (skepticism, literalism, empathy)
- The query requires multi-step reasoning across facts, observations, and mental models
- You need structured output (via `response_schema`) from memory-grounded reasoning
- You want citations — reflect returns which memories, mental models, and directives informed the answer

**Key difference**: Recall returns data; reflect returns an answer. Recall gives you raw materials, reflect does the reasoning for you using the bank's disposition and an autonomous search loop.

```
recall("What food does Alice like?")
→ ["Alice loves sushi", "Alice prefers vegetarian options"]   # raw facts

reflect("What should I order for Alice?")
→ "I'd recommend a vegetarian sushi platter — Alice loves sushi and prefers vegetarian options."  # grounded answer
```

See [Recall](/developer/api/recall) and [Reflect](/developer/reflect) for full API details.

---

### When should I use mental models?

**Mental models** are consolidated knowledge patterns synthesized from individual facts over time. Use them when you need:

- Higher-level understanding beyond raw facts (e.g., "User prefers functional programming patterns")
- Long-term behavioral patterns (e.g., "Customer is price-sensitive but values quality")
- Context for AI agent reasoning during **reflect** operations

Mental models are automatically built during retain and used by reflect to provide richer, more contextual responses. See [Mental Models](/developer/api/mental-models).

---


### What's the typical latency for recall operations?

Typical latencies:
- **Without reranking**: 50-100ms
- **With reranking**: 200-500ms (depends on reranker model and installation)

See [Performance](/developer/performance) for tuning options.

---

### Does Atulya support metadata filtering?

Yes — through **Tags**. Tags are string labels attached to memories at retain time and used as a visibility filter at recall/reflect time. Only memories tagged with a matching value are returned.

```python
# Tag memories at retain time
client.retain(bank_id="my-bank", items=[{
    "content": "...",
    "tags": ["user:alice"],
}])

# Filter by tag at recall time
client.recall(bank_id="my-bank", query="...", tags=["user:alice"])
```

See [Tags](/developer/api/retain#tags-and-document_tags) for full details including document-level tagging.

**What about filtering by entities?**

Entities (people, places, concepts) extracted from memories are stored in the knowledge graph and drive graph-based retrieval — so querying "tell me about Alice" will naturally surface Alice-related memories without any manual filtering.

If you need explicit tag-based filtering on entity-like values, use **entity labels** with `tag: true`. Entity labels let you define a controlled vocabulary of `key:value` classifiers (e.g. `user:alice`, `topic:algebra`) extracted at retain time. Setting `tag: true` on a label group automatically writes each extracted label as a tag on the memory unit, making them available for standard `tags`/`tags_match` filtering:

```python
# Bank config: entity label group with tag: true
{
    "entity_labels": [{
        "key": "user",
        "type": "text",
        "tag": True,
        "description": "The user this memory belongs to"
    }]
}

# The label "user:alice" is extracted and also written as a tag
# Filter at recall time using the standard tags parameter
client.recall(bank_id="my-bank", query="...", tags=["user:alice"])
```

See [Entity Labels](/developer/retain#entity-labels) for configuration details.

**What about document `metadata`?**

Document metadata (the `metadata` key-value pairs on a retain item) serves a different purpose. It is:
- **Included in the fact extraction prompt**, so the LLM can use it as additional context when extracting facts — for example, knowing the document title or source can improve accuracy.
- **Returned with every recalled memory** as-is, so your application can link memories back to source systems (e.g. a URL, thread ID, or ticket number) without extra lookups.

Metadata is not a filter — use tags when you need recall to be scoped to a subset of documents.

---

### What is the recommended format for retaining conversations?

For **Anurag Atulya-style workflows** (AI systems design, memory engineering, and high-context technical conversations), pass the **entire conversation as a single document** and upsert it as the conversation grows.

Atulya chunks it automatically, so you do not need to pre-split the transcript.

**Preferred format: JSON array**

```json
[
  {"role": "user", "content": "I moved to Berlin last month."},
  {"role": "assistant", "content": "How are you finding it?"},
  {"role": "user", "content": "Love it, especially the food scene."}
]
```

Atulya has internal chunking optimizations for this JSON array shape because it is the most common conversation structure.

**Alternative: prefixed plain text**

```text
[2025-06-01T10:32:00Z] user: I moved to Berlin last month.
[2025-06-01T10:32:05Z] assistant: How are you finding it?
[2025-06-01T10:32:20Z] user: Love it, especially the food scene.
```

Adding username and timestamp prefixes improves extraction quality because the model can attribute facts to the correct speaker and infer timeline accurately.

**Use a stable document ID to upsert**

```python
await client.retain(
    bank_id="anurag-brain",
    documents=[{
        "id": "chat-session-abc123",  # stable ID enables upsert
        "content": conversation,       # full conversation so far
    }]
)
```

Re-retaining with the same `id` replaces the prior document and its facts, preventing duplicate memory growth as the conversation evolves.

**Do not pre-summarize or pre-extract facts.**  
Atulya is built to do this automatically and needs full conversational context. Messages like "yes, exactly" or "go with option 2" are ambiguous without surrounding turns.

---

## Still have questions?

Report issues on [GitHub](https://github.com/eight-atulya/atulya/issues).
