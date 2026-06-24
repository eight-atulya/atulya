---
title: "Persistent agent memory over MCP"
authors: [atulya]
date: 2026-03-04
tags: [mcp, memory, agents, docker, tutorial]
hide_table_of_contents: true
slug: mcp-agent-memory
---

Give any MCP client structured long-term memory: `retain`, `recall`, `reflect`, and mental models. One Docker command for local stack, or Atulya Cloud over HTTPS.

<!-- truncate -->

## TL;DR

- Agents are stateless by default; Atulya adds a memory bank per MCP URL path
- Not a vector dump: fact extraction, entities, graph, multi-strategy recall, reranking
- Open source: [github.com/eight-atulya/atulya](https://github.com/eight-atulya/atulya)

## Architecture

```
MCP Client (Claude, Cursor, VS Code, …)
        │ HTTP MCP
        ▼
   Atulya API
        ├── Memory engine
        ├── Fact extraction + entities
        ├── Embeddings + reranker
        ├── Graph traversal
        └── PostgreSQL + pgvector
```

## Start locally

```bash
docker run --rm -it --pull always -p 8888:8888 -p 9999:9999 \
  -e ATULYA_API_LLM_API_KEY=YOUR_LLM_API_KEY \
  -v $HOME/.atulya-docker:/home/atulya/.pg0 \
  ghcr.io/eight-atulya/atulya:latest
```

Non-OpenAI provider example:

```bash
docker run --rm -it --pull always -p 8888:8888 -p 9999:9999 \
  -e ATULYA_API_LLM_PROVIDER=gemini \
  -e ATULYA_API_LLM_API_KEY=YOUR_GEMINI_API_KEY \
  -e ATULYA_API_LLM_MODEL=gemini-2.5-flash \
  -v $HOME/.atulya-docker:/home/atulya/.pg0 \
  ghcr.io/eight-atulya/atulya:latest
```

MCP endpoint: `http://localhost:8888/mcp/your_bank_id/`

Persist data with `-v`. Port 9999 is optional admin UI.

## Atulya Cloud

```json
{
  "mcpServers": {
    "atulya": {
      "type": "http",
      "url": "https://api.atulya.eightengine.com/mcp/your_bank_id/",
      "headers": { "Authorization": "Bearer YOUR_API_KEY" }
    }
  }
}
```

## Connect clients

```json
{
  "mcpServers": {
    "atulya": {
      "type": "http",
      "url": "http://localhost:8888/mcp/your_bank_id/"
    }
  }
}
```

| Client | Config location |
|--------|-----------------|
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) |
| Cursor | `.cursor/mcp.json` or `~/.cursor/mcp.json` |
| VS Code | `.vscode/mcp.json` (`"servers"` key) |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` (`serverUrl`) |

Claude Code CLI:

```bash
claude mcp add --transport http atulya http://localhost:8888/mcp/your_bank_id/
```

Ask: *"What memory tools do you have?"* You should see retain, recall, reflect, mental model tools, and bank utilities.

## Core tools

**Retain** stores and extracts structure. Example input: *"Alice from engineering recommended Postgres 16 for JSONB"* → fact, resolved entity, temporal index, embeddings.

**Recall** runs semantic, BM25, graph, and temporal paths in parallel, then reranks.

**Reflect** synthesizes across memories with an LLM for connect-the-dots questions.

**Mental models** are living summaries that can refresh when consolidation runs.

## Memory banks

Path segment = bank ID. Banks are isolated (`my-project`, `team-knowledge`, per-user in multi-agent setups). Created on first use.

Multi-bank mode: connect to `/mcp/` with `bank_id` on each tool plus `list_banks`, `create_bank`, etc.

## Pitfalls

- **Retain is async.** Wait a few seconds before recalling complex ingests.
- **Recall token cap** defaults to 4096 tokens of memory content.
- **Mental model generation** is async; poll `operation_id` if needed.
- **`ATULYA_API_LLM_API_KEY`** powers Atulya's extraction/reflect, not necessarily your chat model. A fast cheap model is fine.

## When it fits

- Structured memory across sessions and clients
- Entity + temporal retrieval without building RAG yourself
- Agents that accumulate knowledge over weeks

## Next steps

- Build memory by using the agent normally; explicit "remember that …" works too
- Create mental models for architecture or preference summaries
- [Python](/sdks/python) and [TypeScript](/sdks/nodejs) SDKs for app integration
- Docs: [atulya.eightengine.com](https://atulya.eightengine.com)
- [Atulya Cloud](https://ui.atulya.eightengine.com/signup)
