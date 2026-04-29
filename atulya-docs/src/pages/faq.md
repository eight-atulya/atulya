---
title: Frequently Asked Questions
description: Common questions about Atulya — plain English answers
hide_table_of_contents: false
---

# Frequently Asked Questions

### What is Atulya?

Your AI agent forgets everything between conversations. Every session starts blank.

Atulya fixes that. It gives your agent a persistent memory — facts it remembers, relationships it tracks, patterns it notices over time. Like giving your agent a brain instead of a notepad.

Three things happen:
- **retain** — agent learns something, Atulya stores it
- **recall** — agent needs something, Atulya surfaces the right facts
- **reflect** — agent asks a question, Atulya reasons across everything it remembers and gives an answer

---

### How is this different from RAG?

RAG stores documents and searches them. It is a search engine.

Atulya stores **facts extracted from documents** — not the raw text. It builds a knowledge graph of who said what, when, and how those things relate. It gets smarter over time. RAG stays the same.

| | RAG | Atulya |
|---|---|---|
| What it stores | Raw text chunks | Extracted facts + relationships |
| Gets smarter over time | No | Yes |
| Knows who is who | No | Yes |
| Reasons across memories | No | Yes |
| Best for | Document Q&A | Agent memory |

See [RAG vs Memory](/developer/rag-vs-atulya) for a deeper comparison.

---

### Why not just use a vector database?

A vector database finds similar text. That is all it does.

Atulya knows **what** the text means, **who** it is about, **when** things happened, and how facts **contradict or reinforce each other**. Vector search is the plumbing inside Atulya — but Atulya is the whole house.

---

### Which LLM providers work with Atulya?

All the major ones: OpenAI, Anthropic, Google Gemini, Groq.

Local models too — Ollama and LM Studio work out of the box.

```bash
# Ollama example
ATULYA_API_LLM_PROVIDER=ollama
ATULYA_API_LLM_MODEL=llama3.1
ATULYA_API_LLM_BASE_URL=http://localhost:11434
```

Any OpenAI-compatible endpoint works (Together AI, Fireworks, DeepInfra, etc.). See [Models](/developer/models) for the full list.

---

### Which model should I use?

Start with **`gpt-4.1-nano` on OpenAI** (best accuracy) or **`openai/gpt-oss-20b` on Groq** (best speed + cost).

[Full live leaderboard →](https://benchmarks.atulya.eightengine.com/)

| Rank | Model | Provider | Score | Quality | Speed | Cost (per 1M) | Reliability |
|:----:|-------|----------|------:|:-------:|:-----:|:-------------:|:-----------:|
| 🥇 1 | `openai/gpt-oss-20b` | Groq | **81.2** | 83.9 · 84% | 7.5s · 2434 tok/s | $0.05/$0.08 | 100% |
| 🥈 2 | `gpt-4.1-nano` | OpenAI | **79.7** | 87.2 · 87% | 8.5s · 263 tok/s | $0.07/$0.30 | 100% |
| 🥉 3 | `openai/gpt-oss-120b` | Groq | **79.7** | 84.7 · 85% | 8.1s · 1604 tok/s | $0.10/$0.16 | 100% |
| 4 | `gpt-4o-mini` | OpenAI | **74.3** | 81.0 · 81% | 9.0s · 183 tok/s | $0.15/$0.60 | 100% |
| 5 | `llama-3.3-70b-versatile` | Groq | **73.7** | 85.5 · 86% | 4.8s · 306 tok/s | $0.59/$0.79 | 84% |
| 6 | `gemini-2.5-flash-lite` | Google | **73.3** | 84.7 · 85% | 15.8s · 621 tok/s | $0.10/$0.40 | 96% |
| 7 | `gpt-4.1-mini` | OpenAI | **73.2** | 86.4 · 86% | 15.4s · 229 tok/s | $0.15/$0.60 | 100% |

---

### Do I need to run my own server?

No. Two options:

1. **Atulya Cloud** — sign up at [ui.atulya.eightengine.com](https://ui.atulya.eightengine.com), no setup needed
2. **Self-hosted** — run it yourself with Docker in ~10 minutes

See [Installation](/developer/installation).

---

### What are the minimum requirements to self-host?

- Python 3.11+
- 4 GB RAM (8 GB recommended)
- An LLM API key — or a local model via Ollama/LM Studio

That is it.

---

### How do I keep different users' memories separate?

Each user gets their own **memory bank** — a completely isolated "brain". No data leaks between banks.

```python
# Alice's brain
client.retain(bank_id="user-alice", ...)

# Bob's brain — completely separate
client.retain(bank_id="user-bob", ...)
```

If you also need to ask questions **across all users** (e.g. "what topics come up most?"), use a single shared bank and tag each memory with the user ID:

```python
client.retain(bank_id="my-app", items=[{
    "content": "...",
    "tags": ["user:alice"],
}])

# Get only Alice's memories
client.recall(bank_id="my-app", query="...", tags=["user:alice"])
```

See [Memory Banks](/developer/api/memory-banks).

---

### What is the difference between retain, recall, and reflect?

Think of it like a human brain:

| Operation | What it does | When to use |
|---|---|---|
| **retain** | Learns and stores new information | After every conversation turn |
| **recall** | Returns raw facts matching a query | When you want to feed memories into your own prompt |
| **reflect** | Reasons across memories and returns a full answer | When you want Atulya to do the thinking |

---

### When should I use recall vs reflect?

**Use recall** when you want the raw facts and will do your own reasoning:
```python
recall("What food does Alice like?")
# → ["Alice loves sushi", "Alice prefers vegetarian options"]
```

**Use reflect** when you want a ready answer:
```python
reflect("What should I order for Alice?")
# → "I'd suggest a vegetarian sushi platter — Alice loves sushi and prefers vegetarian."
```

Rule of thumb: recall is faster (50–500ms), reflect is smarter (1–10s). Use recall for lookups, reflect for reasoning.

See [Recall](/developer/api/recall) and [Reflect](/developer/reflect) for full API details.

---

### How fast is recall?

- Without reranking: **50–100ms**
- With reranking: **200–500ms**

See [Performance](/developer/performance).

---

### Can I filter memories by tag or user?

Yes. Attach tags when you store memories, filter by them when you search:

```python
# Store with a tag
client.retain(bank_id="my-bank", items=[{
    "content": "Alice prefers dark roast coffee.",
    "tags": ["user:alice"],
}])

# Retrieve only Alice's memories
client.recall(bank_id="my-bank", query="coffee preferences", tags=["user:alice"])
```

Entities (people, places, concepts) are also tracked automatically in a knowledge graph — querying "tell me about Alice" surfaces Alice-related memories without any manual tagging.

See [Tags](/developer/api/retain#tags-and-document_tags) and [Entity Labels](/developer/retain#entity-labels).

---

### What format should I use for conversations?

Pass the full conversation as a JSON array. Atulya handles the chunking:

```json
[
  {"role": "user", "content": "I moved to Berlin last month."},
  {"role": "assistant", "content": "How are you finding it?"},
  {"role": "user", "content": "Love it, especially the food scene."}
]
```

Use a **stable document ID** so re-retaining the same conversation replaces the old memory instead of duplicating it:

```python
client.retain(
    bank_id="user-alice",
    documents=[{
        "id": "chat-session-abc123",  # same ID = update, not duplicate
        "content": conversation,
    }]
)
```

Do not pre-summarize or pre-extract facts yourself — Atulya does that better with full context.

---

### What is a mental model?

A mental model is a higher-level pattern Atulya builds by connecting individual facts over time.

Example: from many separate facts — "Alice skips lunch often", "Alice orders coffee at 2pm", "Alice works late on Fridays" — Atulya might form the mental model: *"Alice is a high-output, low-maintenance worker with irregular eating patterns."*

That pattern then informs future reflect answers without needing to spell it out every time. Mental models are built automatically. See [Mental Models](/developer/api/mental-models).  
Atulya is built to do this automatically and needs full conversational context. Messages like "yes, exactly" or "go with option 2" are ambiguous without surrounding turns.

---

## Still have questions?

Report issues on [GitHub](https://github.com/eight-atulya/atulya/issues).
