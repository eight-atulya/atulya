
# Quick Start

Get up and running with Atulya in 60 seconds.

{/* Import raw source files */}

## Start the API Server

### pip (API only)

```bash
pip install atulya-api
export OPENAI_API_KEY=sk-xxx
export ATULYA_API_LLM_API_KEY=$OPENAI_API_KEY

atulya-api
```

API available at [http://localhost:8888](http://localhost:8888/docs)

### Docker (Full Experience)

```bash

export OPENAI_API_KEY=sk-xxx

docker run --rm -it --pull always -p 8888:8888 -p 9999:9999 \
  -e ATULYA_API_LLM_API_KEY=$OPENAI_API_KEY \
  -v $HOME/.atulya-docker:/home/atulya/.pg0 \
  ghcr.io/eight-atulya/atulya:latest
```

- **API**: http://localhost:8888
- **Control Plane** (Web UI): http://localhost:9999

> **💡 LLM Provider**
> 
Atulya requires an LLM with structured output support. Recommended: **Groq** with `gpt-oss-20b` for fast, cost-effective inference.
See [LLM Providers](/developer/models#llm) for more details.
---

## Use the Client

### Python

```bash
pip install atulya-client
```

```python
from atulya_client import Atulya

client = Atulya(base_url="http://localhost:8888")

# Retain: Store information
client.retain(bank_id="my-bank", content="Alice works at Google as a software engineer")

# Recall: Search memories
client.recall(bank_id="my-bank", query="What does Alice do?")

# Reflect: Generate disposition-aware response
client.reflect(bank_id="my-bank", query="Tell me about Alice")
```

### Node.js

```bash
npm install @eight-atulya/atulya-client
```

```javascript
import { AtulyaClient } from '@eight-atulya/atulya-client';

const client = new AtulyaClient({ baseUrl: 'http://localhost:8888' });

// Retain: Store information
await client.retain('my-bank', 'Alice works at Google as a software engineer');

// Recall: Search memories
await client.recall('my-bank', 'What does Alice do?');

// Reflect: Generate response
await client.reflect('my-bank', 'Tell me about Alice');
```

### CLI

```bash
curl -fsSL https://atulya.eightengine.com/get-cli | bash
```

```bash
# Retain: Store information
atulya memory retain my-bank "Alice works at Google as a software engineer"

# Recall: Search memories
atulya memory recall my-bank "What does Alice do?"

# Reflect: Generate response
atulya memory reflect my-bank "Tell me about Alice"
```

---

## What's Happening

| Operation | What it does |
|-----------|--------------|
| **Retain** | Content is processed, facts are extracted, entities are identified and linked in a knowledge graph |
| **Recall** | Four search strategies (semantic, keyword, graph, temporal) run in parallel to find relevant memories |
| **Reflect** | Retrieved memories are used to generate a disposition-aware response |

---

## Next Steps

- [**Retain**](./retain) — Advanced options for storing memories
- [**Recall**](./recall) — Search and retrieval strategies
- [**Reflect**](./reflect) — Disposition-aware reasoning
- [**Memory Banks**](./memory-banks) — Configure disposition and mission
- [**Server Deployment**](/developer/installation) — Docker Compose, Helm, and production setup
