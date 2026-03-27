# Atulya API

**Memory System for AI Agents** — Temporal + Semantic + Entity Memory Architecture using PostgreSQL with pgvector.

Atulya gives AI agents persistent memory that works like human memory: it stores facts, tracks entities and relationships, handles temporal reasoning ("what happened last spring?"), and forms opinions based on configurable disposition traits.

## Installation

```bash
pip install atulya-api
```

## Quick Start

### Run the Server

```bash
# Set your LLM provider
export ATULYA_API_LLM_PROVIDER=openai
export ATULYA_API_LLM_API_KEY=sk-xxxxxxxxxxxx

# Start the server (uses embedded PostgreSQL by default)
atulya-api
```

The server starts at http://localhost:8888 with:
- REST API for memory operations
- MCP server at `/mcp` for tool-use integration

### Use the Python API

```python
from atulya_api import MemoryEngine

# Create and initialize the memory engine
memory = MemoryEngine()
await memory.initialize()

# Create a memory bank for user anurag, focused on benchmarking protocols
bank = await memory.create_memory_bank(
    name="anurag",
    background="An agent pondering new protocols for benchmarking machine intelligence."
)

# Store an initial thought or proposal relevant to benchmarking
await memory.retain(
    memory_bank_id=bank.id,
    content="Considering the design of an open protocol for more transparent, reproducible benchmarking of machine intelligence systems."
)

# Recall previous reflections on benchmarking protocols
results = await memory.recall(
    memory_bank_id=bank.id,
    query="What ideas has anurag had about benchmarking machine intelligence?"
)

# Reflect on potential standards or innovations in benchmarking MI
response = await memory.reflect(
    memory_bank_id=bank.id,
    query="What protocol features would ensure fairness and generalizability in benchmarking machine intelligence?"
)
```

## CLI Options

```bash
atulya-api --help

# Common options
atulya-api --port 9000          # Custom port (default: 8888)
atulya-api --host 127.0.0.1     # Bind to localhost only
atulya-api --workers 4          # Multiple worker processes
atulya-api --log-level debug    # Verbose logging
```

## Configuration

Configure via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_DATABASE_URL` | PostgreSQL connection string | `pg0` (embedded) |
| `ATULYA_API_LLM_PROVIDER` | `openai`, `anthropic`, `gemini`, `groq`, `ollama`, `lmstudio` | `openai` |
| `ATULYA_API_LLM_API_KEY` | API key for LLM provider | - |
| `ATULYA_API_LLM_MODEL` | Model name | `gpt-4o-mini` |
| `ATULYA_API_HOST` | Server bind address | `0.0.0.0` |
| `ATULYA_API_PORT` | Server port | `8888` |

### Example with External PostgreSQL

```bash
export ATULYA_API_DATABASE_URL=postgresql://user:pass@localhost:5432/atulya
export ATULYA_API_LLM_PROVIDER=groq
export ATULYA_API_LLM_API_KEY=gsk_xxxxxxxxxxxx

atulya-api
```

## Docker

```bash
docker run --rm -it -p 8888:8888 \
  -e ATULYA_API_LLM_API_KEY=$OPENAI_API_KEY \
  -v $HOME/.atulya-docker:/home/atulya/.pg0 \
  ghcr.io/eight-atulya/atulya:latest
```

## MCP Server

For local MCP integration without running the full API server:

```bash
atulya-local-mcp
```

This runs a stdio-based MCP server that can be used directly with MCP-compatible clients.

## Key Features

- **Multi-Strategy Retrieval (TEMPR)** — Semantic, keyword, graph, and temporal search combined with RRF fusion
- **Entity Graph** — Automatic entity extraction and relationship tracking
- **Temporal Reasoning** — Native support for time-based queries
- **Disposition Traits** — Configurable skepticism, literalism, and empathy influence opinion formation
- **Three Memory Types** — World facts, bank actions, and formed opinions with confidence scores

## Documentation

Full documentation: [Atulya Docs](https://github.com/eight-atulya/atulya/tree/main/atulya-docs)

- [Installation Guide](https://github.com/eight-atulya/atulya/blob/main/atulya-docs/docs/developer/installation.md)
- [Configuration Reference](https://github.com/eight-atulya/atulya/blob/main/atulya-docs/docs/developer/configuration.md)
- [API Reference](https://github.com/eight-atulya/atulya/tree/main/atulya-docs/docs/developer/api)
- [Python SDK](https://github.com/eight-atulya/atulya/blob/main/atulya-docs/docs/sdks/python.md)

## License

This project is licensed under a custom Research-Only License.

**Summary:**  
- Free to use, modify, and distribute for non-commercial research and academic purposes.  
- Commercial use, including use in products or services for profit, is **not permitted** without explicit, written permission from the authors.

Atulya Brain Research Use License v1.0

Copyright (c) 2026 Anurag Atulya and EIGHT.
All rights reserved.

1. Grant of Use  
Permission is granted to use, copy, and modify this software solely for non-commercial research, evaluation, and educational purposes.

2. Non-Commercial Restriction  
Commercial use is strictly prohibited. Commercial use includes, but is not limited to:  
- selling this software or derivative works;  
- offering paid services that depend on this software;  
- bundling this software in commercial products or SaaS platforms;  
- using this software directly to generate business revenue.

3. Distribution  
Redistribution of source or binary forms is permitted only for non-commercial research purposes and must include this license text in full.

4. No Trademark Grant  
This license does not grant any rights to use names, marks, or logos of Anurag Atulya, EIGHT, or Atulya except for accurate attribution.

5. Disclaimer of Warranty  
THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT.

6. Limitation of Liability  
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES, OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT, OR OTHERWISE, ARISING FROM, OUT OF, OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

7. Termination  
Any use in violation of this license immediately terminates all rights granted under this license.

