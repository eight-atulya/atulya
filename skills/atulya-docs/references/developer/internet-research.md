
# Internet Research

Atulya's **Internet Research** workflow gives operators a live-web workbench that stays deliberately separate from memory mutation.

Use it when you need fresh public-web evidence, want to compare raw search snippets against extracted page content, and only then decide whether the result deserves a Retain draft.

## What It Is

The feature spans three layers:

- **API research endpoint**: `/v1/default/banks/{bank_id}/internet/research`
- **Control-plane Internet tab**: quick search, extract, curated clipboard, and draft handoff
- **Cortex internet tools**: optional `web_search` and `web_extract` for local/TUI workflows

The core rule is simple:

- **research is session-only by default**
- **memory changes happen only after explicit retain review**

## Why It Exists

Internet research has a different trust profile from retained memory:

- web evidence can be noisy, contradictory, or stale
- operators often want to compare snippets, extracted markdown, and synthesized answers before saving anything
- LLM-powered web research should not silently become durable memory

This workflow keeps those stages separate:

1. Search the public web
2. Inspect and curate findings
3. Build a retain draft
4. Review the draft in Retain
5. Persist it only if it clears human review

## Stack

The feature uses an optional connector stack:

- **SearXNG** for metasearch
- **Firecrawl** for readable markdown extraction

For local setup, use:

```bash
docker/docker-compose/internet-search/docker-compose.yaml
```

See [Configuration](./configuration#internet-research-stack) for the exact environment variables.

## Control Plane Workflow

Open the **Internet** tab inside a bank to access the operator workbench.

### 1. Quick search

Quick search hits the control-plane SearXNG proxy and returns:

- a compact digest for rapid scanning
- the top ranked result list
- direct result selection for extraction

This is the fastest path when you need source discovery rather than a synthesized answer.

### 2. Extract page content

When one result looks promising, the control plane can fetch Firecrawl markdown for that URL.

This is useful when:

- the search snippet is too thin
- you need source wording beyond the search digest
- you want to compare multiple sources before saving anything

### 3. Curate into the research clipboard

The Internet tab includes a browser-persistent clipboard per bank.

Use it to collect:

- SearXNG snippets
- Firecrawl extracts
- your own operator notes

That clipboard is the staging area for later Retain work.

### 4. Send to Retain Draft

When the clipboard looks good, use **Send to Retain Draft**.

This builds a draft that includes:

- combined curated content
- a generated document id
- draft tags
- metadata about the research session
- lightweight entity hints

Nothing is written yet. The draft is handed off to the Retain dialog for human review.

### Optional AI draft enrichment

The control plane can optionally run a small Reflect pass to improve:

- context
- tags
- entity hints
- metadata

That enrichment is guarded by deterministic checks before it is accepted. If the confidence or grounding checks fail, the system falls back to the stable deterministic draft.

## API Research Endpoint

The API endpoint is designed for **live web only** reasoning:

```http
POST /v1/default/banks/{bank_id}/internet/research
```

Important behavior:

- uses the bank's Reflect LLM configuration
- authenticates and validates like other bank-scoped reads
- does **not** read memory-bank content
- does **not** write memory-bank content

### Request

```json
{
  "query": "Latest stable release of Python",
  "budget": "mid",
  "max_tokens": 4096,
  "include": {
    "tool_calls": {
      "output": true
    }
  }
}
```

### Response

```json
{
  "text": "Markdown answer synthesized from live web tools",
  "source_urls": [
    "https://www.python.org/downloads/"
  ],
  "writes_to_bank": false,
  "usage": {
    "input_tokens": 1234,
    "output_tokens": 321,
    "total_tokens": 1555
  },
  "trace": {
    "tool_calls": [],
    "llm_calls": []
  }
}
```

### Tooling model

The live-web agent is intentionally narrow:

- it starts from **`web_search`**
- it can optionally use **`web_extract`** for deeper page detail
- it finishes with a structured `done(...)` answer

That keeps the research loop efficient and reduces raw-page context bloat.

## Cortex Internet Tools

When enabled in Cortex config, local operators can use:

- `web_search`
- `web_extract`

Those tools are designed with token discipline in mind:

- search first
- extract only when the snippet is insufficient
- avoid raw `web_fetch` on search-engine result pages

This keeps local tool use aligned with the control-plane and API research model.

## Configuration Notes

The API and control plane can point at different connector hosts.

Common patterns:

- **single-host local dev**: both use `127.0.0.1`
- **split deployment**: API reaches one connector network, control plane reaches another
- **managed connectors**: both point at your hosted SearXNG and Firecrawl services

See [Services](./services#optional-internet-stack) and [Configuration](./configuration#internet-research-stack) for deployment details.

## When To Use It

Choose **Internet Research** when:

- you need fresh public-web evidence
- you are not ready to retain that evidence yet
- you want operator review between research and memory mutation

Choose **Reflect** when:

- the answer should come from what the bank already knows
- you want mission-aware reasoning over retained memory

Choose **Retain** when:

- the evidence has been curated and deserves durable memory
- you want that information to become part of future Recall and Reflect flows
