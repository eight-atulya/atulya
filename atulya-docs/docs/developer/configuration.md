# Configuration

Complete reference for configuring Atulya services through environment variables.

Atulya has two services, each with its own configuration prefix:

| Service | Prefix | Description |
|---------|--------|-------------|
| **API Service** | `ATULYA_API_*` | Core memory engine |
| **Control Plane** | `ATULYA_CP_*` | Web UI |

---

## API Service

The API service handles all memory operations (retain, recall, reflect).

### Database

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_DATABASE_URL` | PostgreSQL connection string | `pg0` (embedded) |
| `ATULYA_API_DATABASE_SCHEMA` | PostgreSQL schema name for tables | `public` |
| `ATULYA_API_RUN_MIGRATIONS_ON_STARTUP` | Run database migrations on API startup | `true` |

If not provided, the server uses embedded `pg0` — convenient for development but not recommended for production.

The `DATABASE_SCHEMA` setting allows you to use a custom PostgreSQL schema instead of the default `public` schema. This is useful for:
- Multi-database setups where you want Atulya tables in a dedicated schema
- Hosting platforms (e.g., Supabase) where `public` schema is reserved or shared
- Organizational preferences for schema naming conventions

```bash
# Example: Using a custom schema
export ATULYA_API_DATABASE_URL=postgresql://user:pass@host:5432/dbname
export ATULYA_API_DATABASE_SCHEMA=atulya
```

Migrations will automatically create the schema if it doesn't exist and create all tables in the configured schema.

### Database Connection Pool

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_DB_POOL_MIN_SIZE` | Minimum connections in the pool | `5` |
| `ATULYA_API_DB_POOL_MAX_SIZE` | Maximum connections in the pool | `100` |
| `ATULYA_API_DB_COMMAND_TIMEOUT` | PostgreSQL command timeout in seconds | `60` |
| `ATULYA_API_DB_ACQUIRE_TIMEOUT` | Connection acquisition timeout in seconds | `30` |

For high-concurrency workloads, increase `DB_POOL_MAX_SIZE`. Each concurrent recall/think operation can use 2-4 connections.

To run migrations manually (e.g., before starting the API), use the admin CLI:

```bash
atulya-admin run-db-migration
# Or for a specific schema:
atulya-admin run-db-migration --schema tenant_acme
```

### Vector Extension

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_VECTOR_EXTENSION` | Vector index algorithm: `pgvector`, `vchord`, or `pgvectorscale` | `pgvector` |

Atulya supports three PostgreSQL vector extensions:

#### **pgvector** (HNSW - default)
- In-memory index using Hierarchical Navigable Small World algorithm
- Works well for most embeddings and dataset sizes
- Fast for small-medium datasets (&lt;10M vectors)
- Higher memory usage for large datasets
- Most widely deployed and supported

#### **pgvectorscale** (DiskANN - recommended for scale) ⭐
- Disk-based index using StreamingDiskANN algorithm
- **28x lower p95 latency** and **16x higher throughput** vs dedicated vector DBs
- **60-75% cost reduction** at scale (SSDs cheaper than RAM)
- Superior filtering performance with streaming retrieval model
- Optimized for large datasets (10M+ vectors)
- Supports both **pgvectorscale** (open source) and **pg_diskann** (Azure)
- **Installation:**
  - Open source/self-hosted: `CREATE EXTENSION vector; CREATE EXTENSION vectorscale CASCADE;`
  - Azure PostgreSQL: `CREATE EXTENSION vector; CREATE EXTENSION pg_diskann CASCADE;`

#### **vchord** (vchordrq)
- Alternative high-performance vector index
- Optimized for high-dimensional embeddings (3000+ dimensions)
- Includes integrated BM25 search capabilities
- Requires `vchord` extension

**When to use pgvectorscale (DiskANN):**
- Large datasets (10M+ vectors) ⭐
- Complex filtering requirements
- Cost-sensitive deployments
- Production workloads requiring high throughput
- When disk I/O is not a bottleneck

**When to use pgvector (HNSW):**
- Small-medium datasets (&lt;10M vectors)
- Maximum query speed when all data fits in memory
- Simple nearest-neighbor queries without filters
- Standard PostgreSQL deployment preference

**When to use vchord:**
- High-dimensional embeddings (3000+ dimensions)
- Want integrated BM25 search
- Already using vchord for text search

**Switching extensions:**

If you need to switch from one extension to another:
1. Set `ATULYA_API_VECTOR_EXTENSION` to your desired extension (`pgvector`, `vchord`, or `pgvectorscale`)
2. If your database has existing data, you'll get an error with migration instructions
3. For empty databases, indexes will be automatically recreated on startup

**Learn more:**
- [HNSW vs. DiskANN comparison](https://www.tigerdata.com/learn/hnsw-vs-diskann)
- [pgvectorscale GitHub](https://github.com/timescale/pgvectorscale)

### Text Search Extension

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_TEXT_SEARCH_EXTENSION` | Text search backend: `native`, `vchord`, or `pg_textsearch` | `native` |

Atulya supports three text search backends for BM25 keyword retrieval:
- **native**: PostgreSQL's built-in full-text search (`tsvector` + GIN indexes)
- **vchord**: VectorChord BM25 (`bm25vector` + BM25 indexes) - requires `vchord_bm25` extension
- **pg_textsearch**: Timescale BM25 (text columns + BM25 indexes) - requires `pg_textsearch` extension

**When to use native:**
- Standard PostgreSQL deployment (no extra extensions)
- Simpler setup and wider compatibility
- Works well for most use cases

**When to use vchord:**
- Already using vchord for vector search (good integration)
- Want better BM25 ranking performance
- Need advanced tokenization (uses `llmlingua2` tokenizer)

**When to use pg_textsearch:**
- Want industry-standard BM25 ranking with better relevance than native PostgreSQL
- Need efficient top-K queries with Block-Max WAND optimization
- Prefer lower memory footprint compared to vchord
- Already using Timescale or have `pg_textsearch` available

**Switching backends:**

To switch between backends:
1. Set `ATULYA_API_TEXT_SEARCH_EXTENSION` to your desired backend (`native`, `vchord`, or `pg_textsearch`)
2. If your database has existing data, you'll get an error with migration instructions
3. For empty databases, the columns/indexes will be automatically recreated on startup

**Note:** VectorChord uses the `llmlingua2` tokenizer for multilingual support, while native and pg_textsearch use PostgreSQL's English tokenizer.

### LLM Provider

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_LLM_PROVIDER` | Provider: `openai`, `openai-codex`, `claude-code`, `anthropic`, `gemini`, `groq`, `ollama`, `lmstudio`, `vertexai` | `openai` |
| `ATULYA_API_LLM_API_KEY` | API key for LLM provider | - |
| `ATULYA_API_LLM_MODEL` | Model name | `gpt-5-mini` |
| `ATULYA_API_LLM_BASE_URL` | Custom LLM endpoint | Provider default |
| `ATULYA_API_LLM_MAX_CONCURRENT` | Max concurrent LLM requests | `32` |
| `ATULYA_API_LLM_MAX_RETRIES` | Max retry attempts for LLM API calls | `10` |
| `ATULYA_API_LLM_INITIAL_BACKOFF` | Initial retry backoff in seconds (exponential backoff) | `1.0` |
| `ATULYA_API_LLM_MAX_BACKOFF` | Max retry backoff cap in seconds | `60.0` |
| `ATULYA_API_LLM_TIMEOUT` | LLM request timeout in seconds | `120` |
| `ATULYA_API_LLM_GROQ_SERVICE_TIER` | Groq service tier: `on_demand`, `flex`, `auto` | `auto` |
| `ATULYA_API_LLM_OPENAI_SERVICE_TIER` | OpenAI service tier: `flex` for 50% cost savings (OpenAI Flex Processing) | None (default) |

**Provider Examples**

```bash
# Groq (recommended for fast inference)
export ATULYA_API_LLM_PROVIDER=groq
export ATULYA_API_LLM_API_KEY=gsk_xxxxxxxxxxxx
export ATULYA_API_LLM_MODEL=openai/gpt-oss-20b
# For free tier users: override to on_demand if you get service_tier errors
# export ATULYA_API_LLM_GROQ_SERVICE_TIER=on_demand

# OpenAI
export ATULYA_API_LLM_PROVIDER=openai
export ATULYA_API_LLM_API_KEY=sk-xxxxxxxxxxxx
export ATULYA_API_LLM_MODEL=gpt-4o
# Optional: Use Flex Processing for 50% cost savings (with variable latency)
# export ATULYA_API_LLM_OPENAI_SERVICE_TIER=flex

# Gemini
export ATULYA_API_LLM_PROVIDER=gemini
export ATULYA_API_LLM_API_KEY=xxxxxxxxxxxx
export ATULYA_API_LLM_MODEL=gemini-2.0-flash

# Anthropic
export ATULYA_API_LLM_PROVIDER=anthropic
export ATULYA_API_LLM_API_KEY=sk-ant-xxxxxxxxxxxx
export ATULYA_API_LLM_MODEL=claude-sonnet-4-20250514

# Vertex AI (Google Cloud - uses native genai SDK)
export ATULYA_API_LLM_PROVIDER=vertexai
export ATULYA_API_LLM_MODEL=gemini-2.0-flash-001
export ATULYA_API_LLM_VERTEXAI_PROJECT_ID=your-gcp-project-id
export ATULYA_API_LLM_VERTEXAI_REGION=us-central1
# Optional: use ADC (gcloud auth application-default login) or provide service account key:
# export ATULYA_API_LLM_VERTEXAI_SERVICE_ACCOUNT_KEY=/path/to/service-account-key.json

# Ollama (local, no API key)
export ATULYA_API_LLM_PROVIDER=ollama
export ATULYA_API_LLM_BASE_URL=http://localhost:11434/v1
export ATULYA_API_LLM_MODEL=llama3

# LM Studio (local, no API key)
export ATULYA_API_LLM_PROVIDER=lmstudio
export ATULYA_API_LLM_BASE_URL=http://localhost:1234/v1
export ATULYA_API_LLM_MODEL=your-local-model

# OpenAI-compatible endpoint
export ATULYA_API_LLM_PROVIDER=openai
export ATULYA_API_LLM_BASE_URL=https://your-endpoint.com/v1
export ATULYA_API_LLM_API_KEY=your-api-key
export ATULYA_API_LLM_MODEL=your-model-name

# OpenAI Codex (ChatGPT Plus/Pro subscription - uses OAuth, no API key needed)
export ATULYA_API_LLM_PROVIDER=openai-codex
export ATULYA_API_LLM_MODEL=gpt-5.2-codex
# No API key needed - uses OAuth tokens from ~/.codex/auth.json

# Claude Code (Claude Pro/Max subscription - uses OAuth, no API key needed)
export ATULYA_API_LLM_PROVIDER=claude-code
export ATULYA_API_LLM_MODEL=claude-sonnet-4-5-20250929
# No API key needed - uses claude auth login credentials
```

:::tip OpenAI Codex, Claude Code & Vertex AI Setup
For detailed setup instructions for **OpenAI Codex** (ChatGPT Plus/Pro), **Claude Code** (Claude Pro/Max), and **Vertex AI** (Google Cloud), see the [Models documentation](./models#openai-codex-setup-chatgpt-pluspro).
:::

### Per-Operation LLM Configuration

Different memory operations have different requirements. **Retain** (fact extraction) benefits from models with strong structured output capabilities, while **Reflect** (reasoning/response generation) can use lighter, faster models. Configure separate LLM models for each operation to optimize for cost and performance.

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_RETAIN_LLM_PROVIDER` | LLM provider for retain operations | Falls back to `ATULYA_API_LLM_PROVIDER` |
| `ATULYA_API_RETAIN_LLM_API_KEY` | API key for retain LLM | Falls back to `ATULYA_API_LLM_API_KEY` |
| `ATULYA_API_RETAIN_LLM_MODEL` | Model for retain operations | Falls back to `ATULYA_API_LLM_MODEL` |
| `ATULYA_API_RETAIN_LLM_BASE_URL` | Base URL for retain LLM | Falls back to `ATULYA_API_LLM_BASE_URL` |
| `ATULYA_API_RETAIN_LLM_MAX_CONCURRENT` | Max concurrent requests for retain | Falls back to `ATULYA_API_LLM_MAX_CONCURRENT` |
| `ATULYA_API_RETAIN_LLM_MAX_RETRIES` | Max retries for retain | Falls back to `ATULYA_API_LLM_MAX_RETRIES` |
| `ATULYA_API_RETAIN_LLM_INITIAL_BACKOFF` | Initial backoff for retain retries (seconds) | Falls back to `ATULYA_API_LLM_INITIAL_BACKOFF` |
| `ATULYA_API_RETAIN_LLM_MAX_BACKOFF` | Max backoff cap for retain retries (seconds) | Falls back to `ATULYA_API_LLM_MAX_BACKOFF` |
| `ATULYA_API_RETAIN_LLM_TIMEOUT` | Timeout for retain requests (seconds) | Falls back to `ATULYA_API_LLM_TIMEOUT` |
| `ATULYA_API_REFLECT_LLM_PROVIDER` | LLM provider for reflect operations | Falls back to `ATULYA_API_LLM_PROVIDER` |
| `ATULYA_API_REFLECT_LLM_API_KEY` | API key for reflect LLM | Falls back to `ATULYA_API_LLM_API_KEY` |
| `ATULYA_API_REFLECT_LLM_MODEL` | Model for reflect operations | Falls back to `ATULYA_API_LLM_MODEL` |
| `ATULYA_API_REFLECT_LLM_BASE_URL` | Base URL for reflect LLM | Falls back to `ATULYA_API_LLM_BASE_URL` |
| `ATULYA_API_REFLECT_LLM_MAX_CONCURRENT` | Max concurrent requests for reflect | Falls back to `ATULYA_API_LLM_MAX_CONCURRENT` |
| `ATULYA_API_REFLECT_LLM_MAX_RETRIES` | Max retries for reflect | Falls back to `ATULYA_API_LLM_MAX_RETRIES` |
| `ATULYA_API_REFLECT_LLM_INITIAL_BACKOFF` | Initial backoff for reflect retries (seconds) | Falls back to `ATULYA_API_LLM_INITIAL_BACKOFF` |
| `ATULYA_API_REFLECT_LLM_MAX_BACKOFF` | Max backoff cap for reflect retries (seconds) | Falls back to `ATULYA_API_LLM_MAX_BACKOFF` |
| `ATULYA_API_REFLECT_LLM_TIMEOUT` | Timeout for reflect requests (seconds) | Falls back to `ATULYA_API_LLM_TIMEOUT` |
| `ATULYA_API_CONSOLIDATION_LLM_PROVIDER` | LLM provider for observation consolidation | Falls back to `ATULYA_API_LLM_PROVIDER` |
| `ATULYA_API_CONSOLIDATION_LLM_API_KEY` | API key for consolidation LLM | Falls back to `ATULYA_API_LLM_API_KEY` |
| `ATULYA_API_CONSOLIDATION_LLM_MODEL` | Model for consolidation operations | Falls back to `ATULYA_API_LLM_MODEL` |
| `ATULYA_API_CONSOLIDATION_LLM_BASE_URL` | Base URL for consolidation LLM | Falls back to `ATULYA_API_LLM_BASE_URL` |
| `ATULYA_API_CONSOLIDATION_LLM_MAX_CONCURRENT` | Max concurrent requests for consolidation | Falls back to `ATULYA_API_LLM_MAX_CONCURRENT` |
| `ATULYA_API_CONSOLIDATION_LLM_MAX_RETRIES` | Max retries for consolidation | Falls back to `ATULYA_API_LLM_MAX_RETRIES` |
| `ATULYA_API_CONSOLIDATION_LLM_INITIAL_BACKOFF` | Initial backoff for consolidation retries (seconds) | Falls back to `ATULYA_API_LLM_INITIAL_BACKOFF` |
| `ATULYA_API_CONSOLIDATION_LLM_MAX_BACKOFF` | Max backoff cap for consolidation retries (seconds) | Falls back to `ATULYA_API_LLM_MAX_BACKOFF` |
| `ATULYA_API_CONSOLIDATION_LLM_TIMEOUT` | Timeout for consolidation requests (seconds) | Falls back to `ATULYA_API_LLM_TIMEOUT` |

:::tip When to Use Per-Operation Config
- **Retain**: Use models with strong structured output (e.g., GPT-4o, Claude) for accurate fact extraction
- **Reflect**: Use faster/cheaper models (e.g., GPT-4o-mini, Groq) for reasoning and response generation
- **Recall**: Does not use LLM (pure retrieval), so no configuration needed
:::

**Example: Separate Models for Retain and Reflect**

```bash
# Default LLM (used as fallback)
export ATULYA_API_LLM_PROVIDER=openai
export ATULYA_API_LLM_API_KEY=sk-xxxxxxxxxxxx
export ATULYA_API_LLM_MODEL=gpt-4o

# Use GPT-4o for retain (strong structured output)
export ATULYA_API_RETAIN_LLM_MODEL=gpt-4o

# Use faster/cheaper model for reflect
export ATULYA_API_REFLECT_LLM_PROVIDER=groq
export ATULYA_API_REFLECT_LLM_API_KEY=gsk_xxxxxxxxxxxx
export ATULYA_API_REFLECT_LLM_MODEL=llama-3.3-70b-versatile
```

**Example: Tuning Retry Behavior for Rate-Limited APIs**

```bash
# For Anthropic with tight rate limits (10k output tokens/minute)
export ATULYA_API_LLM_PROVIDER=anthropic
export ATULYA_API_LLM_API_KEY=sk-ant-xxxxxxxxxxxx
export ATULYA_API_LLM_MODEL=claude-sonnet-4-20250514

# Reduce concurrent requests for retain to avoid rate limits
export ATULYA_API_RETAIN_LLM_MAX_CONCURRENT=3

# Fail faster with fewer retries
export ATULYA_API_RETAIN_LLM_MAX_RETRIES=3

# Or increase backoff times to wait out rate limit windows
export ATULYA_API_RETAIN_LLM_INITIAL_BACKOFF=2.0  # Start at 2s instead of 1s
export ATULYA_API_RETAIN_LLM_MAX_BACKOFF=120.0    # Cap at 2min instead of 1min
```

### Embeddings

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_EMBEDDINGS_PROVIDER` | Provider: `local`, `tei`, `openai`, `cohere`, `litellm`, or `litellm-sdk` | `local` |
| `ATULYA_API_EMBEDDINGS_LOCAL_MODEL` | Model for local provider | `BAAI/bge-small-en-v1.5` |
| `ATULYA_API_EMBEDDINGS_LOCAL_TRUST_REMOTE_CODE` | Allow loading models with custom code (security risk, disabled by default) | `false` |
| `ATULYA_API_EMBEDDINGS_TEI_URL` | TEI server URL | - |
| `ATULYA_API_EMBEDDINGS_OPENAI_API_KEY` | OpenAI API key (falls back to `ATULYA_API_LLM_API_KEY`) | - |
| `ATULYA_API_EMBEDDINGS_OPENAI_MODEL` | OpenAI embedding model | `text-embedding-3-small` |
| `ATULYA_API_EMBEDDINGS_OPENAI_BASE_URL` | Custom base URL for OpenAI-compatible API (e.g., Azure OpenAI) | - |
| `ATULYA_API_EMBEDDINGS_COHERE_API_KEY` | Cohere API key for embeddings | - |
| `ATULYA_API_EMBEDDINGS_COHERE_MODEL` | Cohere embedding model | `embed-english-v3.0` |
| `ATULYA_API_EMBEDDINGS_COHERE_BASE_URL` | Custom base URL for Cohere-compatible API (e.g., Azure-hosted) | - |
| `ATULYA_API_EMBEDDINGS_LITELLM_API_BASE` | LiteLLM proxy base URL for embeddings | `http://localhost:4000` |
| `ATULYA_API_EMBEDDINGS_LITELLM_API_KEY` | LiteLLM proxy API key for embeddings (optional, depends on proxy config) | - |
| `ATULYA_API_EMBEDDINGS_LITELLM_MODEL` | LiteLLM embedding model (use provider prefix, e.g., `cohere/embed-english-v3.0`) | `text-embedding-3-small` |
| `ATULYA_API_EMBEDDINGS_LITELLM_SDK_API_KEY` | LiteLLM SDK API key for direct embedding provider access | - |
| `ATULYA_API_EMBEDDINGS_LITELLM_SDK_MODEL` | LiteLLM SDK embedding model (use provider prefix, e.g., `cohere/embed-english-v3.0`) | `cohere/embed-english-v3.0` |
| `ATULYA_API_EMBEDDINGS_LITELLM_SDK_API_BASE` | Custom base URL for LiteLLM SDK embeddings (optional) | - |

```bash
# Local (default) - uses SentenceTransformers
export ATULYA_API_EMBEDDINGS_PROVIDER=local
export ATULYA_API_EMBEDDINGS_LOCAL_MODEL=BAAI/bge-small-en-v1.5

# Local with custom model requiring trust_remote_code
# WARNING: Only enable trust_remote_code for models you trust (security risk)
# export ATULYA_API_EMBEDDINGS_LOCAL_MODEL=your-custom-model
# export ATULYA_API_EMBEDDINGS_LOCAL_TRUST_REMOTE_CODE=true

# OpenAI - cloud-based embeddings
export ATULYA_API_EMBEDDINGS_PROVIDER=openai
export ATULYA_API_EMBEDDINGS_OPENAI_API_KEY=sk-xxxxxxxxxxxx  # or reuses ATULYA_API_LLM_API_KEY
export ATULYA_API_EMBEDDINGS_OPENAI_MODEL=text-embedding-3-small  # 1536 dimensions

# Azure OpenAI - embeddings via Azure endpoint
export ATULYA_API_EMBEDDINGS_PROVIDER=openai
export ATULYA_API_EMBEDDINGS_OPENAI_API_KEY=your-azure-api-key
export ATULYA_API_EMBEDDINGS_OPENAI_MODEL=text-embedding-3-small
export ATULYA_API_EMBEDDINGS_OPENAI_BASE_URL=https://your-resource.openai.azure.com/openai/deployments/your-deployment

# TEI - HuggingFace Text Embeddings Inference (recommended for production)
export ATULYA_API_EMBEDDINGS_PROVIDER=tei
export ATULYA_API_EMBEDDINGS_TEI_URL=http://localhost:8080

# Cohere - cloud-based embeddings
export ATULYA_API_EMBEDDINGS_PROVIDER=cohere
export ATULYA_API_EMBEDDINGS_COHERE_API_KEY=your-api-key
export ATULYA_API_EMBEDDINGS_COHERE_MODEL=embed-english-v3.0  # 1024 dimensions

# Azure-hosted Cohere - embeddings via custom endpoint
export ATULYA_API_EMBEDDINGS_PROVIDER=cohere
export ATULYA_API_EMBEDDINGS_COHERE_API_KEY=your-azure-api-key
export ATULYA_API_EMBEDDINGS_COHERE_MODEL=embed-english-v3.0
export ATULYA_API_EMBEDDINGS_COHERE_BASE_URL=https://your-azure-cohere-endpoint.com

# LiteLLM proxy - unified gateway for multiple providers
export ATULYA_API_EMBEDDINGS_PROVIDER=litellm
export ATULYA_API_EMBEDDINGS_LITELLM_API_BASE=http://localhost:4000
export ATULYA_API_EMBEDDINGS_LITELLM_API_KEY=your-litellm-key  # optional
export ATULYA_API_EMBEDDINGS_LITELLM_MODEL=text-embedding-3-small  # or cohere/embed-english-v3.0

# LiteLLM SDK - direct API access without proxy server (recommended)
export ATULYA_API_EMBEDDINGS_PROVIDER=litellm-sdk
export ATULYA_API_EMBEDDINGS_LITELLM_SDK_API_KEY=your-provider-api-key
export ATULYA_API_EMBEDDINGS_LITELLM_SDK_MODEL=cohere/embed-english-v3.0

# Supported LiteLLM SDK embedding providers:
# - cohere/embed-english-v3.0 (1024 dimensions)
# - openai/text-embedding-3-small (1536 dimensions)
# - together_ai/togethercomputer/m2-bert-80M-8k-retrieval
# - huggingface/sentence-transformers/all-MiniLM-L6-v2
# - voyage/voyage-2
```

#### Embedding Dimensions

Atulya automatically detects the embedding dimension from the model at startup and adjusts the database schema accordingly. The default model (`BAAI/bge-small-en-v1.5`) produces 384-dimensional vectors, while OpenAI models produce 1536 or 3072 dimensions.

:::warning Dimension Changes
Once memories are stored, you cannot change the embedding dimension without losing data. If you need to switch to a model with different dimensions:

1. **Empty database**: The schema is adjusted automatically on startup
2. **Existing data**: Either delete all memories first, or use a model with matching dimensions

Supported OpenAI embedding dimensions:
- `text-embedding-3-small`: 1536 dimensions
- `text-embedding-3-large`: 3072 dimensions
- `text-embedding-ada-002`: 1536 dimensions (legacy)
:::

### Reranker

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_RERANKER_PROVIDER` | Provider: `local`, `tei`, `cohere`, `zeroentropy`, `flashrank`, `litellm`, `litellm-sdk`, or `rrf` | `local` |
| `ATULYA_API_RERANKER_LOCAL_MODEL` | Model for local provider | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| `ATULYA_API_RERANKER_LOCAL_MAX_CONCURRENT` | Max concurrent local reranking (prevents CPU thrashing under load) | `4` |
| `ATULYA_API_RERANKER_LOCAL_TRUST_REMOTE_CODE` | Allow loading models with custom code (security risk, disabled by default) | `false` |
| `ATULYA_API_RERANKER_TEI_URL` | TEI server URL | - |
| `ATULYA_API_RERANKER_TEI_BATCH_SIZE` | Batch size for TEI reranking | `128` |
| `ATULYA_API_RERANKER_TEI_MAX_CONCURRENT` | Max concurrent TEI reranking requests | `8` |
| `ATULYA_API_RERANKER_COHERE_API_KEY` | Cohere API key for reranking | - |
| `ATULYA_API_RERANKER_COHERE_MODEL` | Cohere rerank model | `rerank-english-v3.0` |
| `ATULYA_API_RERANKER_COHERE_BASE_URL` | Custom base URL for Cohere-compatible API (e.g., Azure-hosted) | - |
| `ATULYA_API_RERANKER_LITELLM_API_BASE` | LiteLLM proxy base URL for reranking | `http://localhost:4000` |
| `ATULYA_API_RERANKER_LITELLM_API_KEY` | LiteLLM proxy API key for reranking (optional, depends on proxy config) | - |
| `ATULYA_API_RERANKER_LITELLM_MODEL` | LiteLLM **proxy** rerank model (use provider prefix, e.g., `cohere/rerank-english-v3.0`) | `cohere/rerank-english-v3.0` |
| `ATULYA_API_RERANKER_LITELLM_SDK_API_KEY` | LiteLLM **SDK** API key for direct reranking (no proxy needed) | - |
| `ATULYA_API_RERANKER_LITELLM_SDK_MODEL` | LiteLLM SDK rerank model (e.g., `deepinfra/Qwen3-reranker-8B`) | `cohere/rerank-english-v3.0` |
| `ATULYA_API_RERANKER_LITELLM_SDK_API_BASE` | Custom API base URL for LiteLLM SDK (optional) | - |
| `ATULYA_API_RERANKER_ZEROENTROPY_API_KEY` | ZeroEntropy API key for reranking | - |
| `ATULYA_API_RERANKER_ZEROENTROPY_MODEL` | ZeroEntropy rerank model (`zerank-2`, `zerank-2-small`) | `zerank-2` |
| `ATULYA_API_RERANKER_FLASHRANK_MODEL` | FlashRank model for fast CPU-based reranking | `ms-marco-MiniLM-L-12-v2` |
| `ATULYA_API_RERANKER_FLASHRANK_CACHE_DIR` | Cache directory for FlashRank models | System default |

```bash
# Local (default) - uses SentenceTransformers CrossEncoder
export ATULYA_API_RERANKER_PROVIDER=local
export ATULYA_API_RERANKER_LOCAL_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2

# Local with custom model requiring trust_remote_code (e.g., jina-reranker-v2)
# WARNING: Only enable trust_remote_code for models you trust (security risk)
export ATULYA_API_RERANKER_PROVIDER=local
export ATULYA_API_RERANKER_LOCAL_MODEL=jinaai/jina-reranker-v2-base-multilingual
export ATULYA_API_RERANKER_LOCAL_TRUST_REMOTE_CODE=true

# TEI - for high-performance inference
export ATULYA_API_RERANKER_PROVIDER=tei
export ATULYA_API_RERANKER_TEI_URL=http://localhost:8081

# Cohere - cloud-based reranking
export ATULYA_API_RERANKER_PROVIDER=cohere
export ATULYA_API_RERANKER_COHERE_API_KEY=your-api-key
export ATULYA_API_RERANKER_COHERE_MODEL=rerank-english-v3.0

# Azure-hosted Cohere - reranking via custom endpoint
export ATULYA_API_RERANKER_PROVIDER=cohere
export ATULYA_API_RERANKER_COHERE_API_KEY=your-azure-api-key
export ATULYA_API_RERANKER_COHERE_MODEL=rerank-english-v3.0
export ATULYA_API_RERANKER_COHERE_BASE_URL=https://your-azure-cohere-endpoint.com

# ZeroEntropy - cloud-based reranking (state-of-the-art accuracy)
export ATULYA_API_RERANKER_PROVIDER=zeroentropy
export ATULYA_API_RERANKER_ZEROENTROPY_API_KEY=your-api-key
export ATULYA_API_RERANKER_ZEROENTROPY_MODEL=zerank-2  # or zerank-2-small

# LiteLLM proxy - unified gateway for multiple reranking providers (requires running LiteLLM proxy server)
export ATULYA_API_RERANKER_PROVIDER=litellm
export ATULYA_API_RERANKER_LITELLM_API_BASE=http://localhost:4000
export ATULYA_API_RERANKER_LITELLM_API_KEY=your-litellm-key  # optional
export ATULYA_API_RERANKER_LITELLM_MODEL=cohere/rerank-english-v3.0  # or voyage/rerank-2, together_ai/...

# LiteLLM SDK - direct API access without proxy (recommended for simplicity)
export ATULYA_API_RERANKER_PROVIDER=litellm-sdk
export ATULYA_API_RERANKER_LITELLM_SDK_API_KEY=your-deepinfra-api-key
export ATULYA_API_RERANKER_LITELLM_SDK_MODEL=deepinfra/Qwen3-reranker-8B  # or cohere/rerank-english-v3.0, etc.
```

#### LiteLLM Proxy vs SDK

- **`litellm`**: Requires running a separate LiteLLM proxy server. Good for centralized configuration, rate limiting, and caching.
- **`litellm-sdk`**: Direct API access without proxy. Simpler setup, lower latency, fewer infrastructure components.

Both support the same providers:
- **Cohere** (`cohere/rerank-english-v3.0`, `cohere/rerank-multilingual-v3.0`)
- **DeepInfra** (`deepinfra/Qwen3-reranker-8B`, `deepinfra/bge-reranker-v2-m3`)
- **Together AI** (`together_ai/Salesforce/Llama-Rank-V1`)
- **HuggingFace** (`huggingface/BAAI/bge-reranker-v2-m3`)
- **Voyage AI** (`voyage/rerank-2`)
- **Jina AI** (`jina_ai/jina-reranker-v2`)
- **AWS Bedrock** (`bedrock/...`)

### Authentication

By default, Atulya runs without authentication. For production deployments, enable API key authentication using the built-in tenant extension:

```bash
# Enable the built-in API key authentication
export ATULYA_API_TENANT_EXTENSION=atulya_api.extensions.builtin.tenant:ApiKeyTenantExtension
export ATULYA_API_TENANT_API_KEY=your-secret-api-key
```

When enabled, all requests must include the API key in the `Authorization` header:

```bash
curl -H "Authorization: Bearer your-secret-api-key" \
  http://localhost:8888/v1/default/banks
```

Requests without a valid API key receive a `401 Unauthorized` response.

:::tip Custom Authentication
For advanced authentication (JWT, OAuth, multi-tenant schemas), implement a custom `TenantExtension`. See the [Extensions documentation](./extensions.md) for details.
:::

### Server

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_HOST` | Bind address | `0.0.0.0` |
| `ATULYA_API_PORT` | Server port | `8888` |
| `ATULYA_API_BASE_PATH` | Base path for API when behind reverse proxy (e.g., `/atulya`) | `""` (root) |
| `ATULYA_API_WORKERS` | Number of uvicorn worker processes | `1` |
| `ATULYA_API_LOG_LEVEL` | Log level: `debug`, `info`, `warning`, `error` | `info` |
| `ATULYA_API_LOG_FORMAT` | Log format: `text` or `json` (structured logging for cloud platforms) | `text` |
| `ATULYA_API_MCP_ENABLED` | Enable MCP server at `/mcp/{bank_id}/` | `true` |

### Retrieval

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_GRAPH_RETRIEVER` | Graph retrieval algorithm: `link_expansion`, `mpfp`, or `bfs` | `link_expansion` |
| `ATULYA_API_RECALL_MAX_CONCURRENT` | Max concurrent recall operations per worker (backpressure) | `32` |
| `ATULYA_API_RECALL_CONNECTION_BUDGET` | Max concurrent DB connections per recall operation | `4` |
| `ATULYA_API_RERANKER_MAX_CANDIDATES` | Max candidates to rerank per recall (RRF pre-filters the rest) | `300` |
| `ATULYA_API_MPFP_TOP_K_NEIGHBORS` | Fan-out limit per node in MPFP graph traversal | `20` |
| `ATULYA_API_MENTAL_MODEL_REFRESH_CONCURRENCY` | Max concurrent mental model refreshes | `8` |
| `ATULYA_API_ENABLE_MENTAL_MODEL_HISTORY` | Track history of content changes to each mental model (previous content + timestamp). Disable to reduce storage if audit trails are not needed. | `true` |

#### Graph Retrieval Algorithms

- **`link_expansion`** (default): Fast, simple graph expansion from semantic seeds via entity co-occurrence and causal links. Target latency under 100ms. Recommended for most use cases.
- **`mpfp`**: Multi-Path Fact Propagation - iterative graph traversal with activation spreading. More thorough but slower.
- **`bfs`**: Breadth-first search from seed facts. Simple but less effective for large graphs.

### Retain

Controls the retain (memory ingestion) pipeline.

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_RETAIN_MAX_COMPLETION_TOKENS` | Max completion tokens for fact extraction LLM calls | `64000` |
| `ATULYA_API_RETAIN_CHUNK_SIZE` | Max characters per chunk for fact extraction. Larger chunks extract fewer LLM calls but may lose context. | `3000` |
| `ATULYA_API_RETAIN_EXTRACTION_MODE` | Fact extraction mode: `concise`, `verbose`, or `custom` | `concise` |
| `ATULYA_API_RETAIN_MISSION` | What this bank should pay attention to during extraction. Steers the LLM without replacing the extraction rules — works alongside any extraction mode. | - |
| `ATULYA_API_RETAIN_CUSTOM_INSTRUCTIONS` | Full prompt override for fact extraction (only used when mode is `custom`). Replaces built-in extraction rules entirely. | - |
| `ATULYA_API_RETAIN_EXTRACT_CAUSAL_LINKS` | Extract causal relationships between facts | `true` |
| `ATULYA_API_RETAIN_BATCH_ENABLED` | Use LLM Batch API for fact extraction (50% cost savings, only with async operations) | `false` |
| `ATULYA_API_RETAIN_BATCH_POLL_INTERVAL_SECONDS` | Batch API polling interval in seconds | `60` |

> **Entity labels** (`entity_labels`) and **free-form entity extraction** (`entities_allow_free_form`) are configured per bank via the [bank config API](/developer/api/memory-banks#retain-configuration), not as global environment variables — each bank can have its own controlled vocabulary. See [Entity Labels](/developer/retain#entity-labels) for details.

#### Customizing retain: when to use what

There are three levels of customization for the retain pipeline. Start with the simplest that covers your needs:

| Goal | Use |
|------|-----|
| Steer what topics to focus on or deprioritize | `ATULYA_API_RETAIN_MISSION` |
| Extract more detail per fact | `ATULYA_API_RETAIN_EXTRACTION_MODE=verbose` |
| Completely replace the extraction rules | `ATULYA_API_RETAIN_EXTRACTION_MODE=custom` + `ATULYA_API_RETAIN_CUSTOM_INSTRUCTIONS` |

**`ATULYA_API_RETAIN_MISSION` — steer extraction without replacing it (recommended starting point)**

Tell the bank what to pay attention to during extraction, in plain language. The mission is injected into the extraction prompt alongside the built-in rules — it narrows focus without replacing the underlying logic. Works with any extraction mode (`concise`, `verbose`, `custom`).

```bash
export ATULYA_API_RETAIN_MISSION="Focus on technical decisions, architecture choices, and team member expertise. Deprioritize social or personal information."
```

**`ATULYA_API_RETAIN_EXTRACTION_MODE=verbose` — more detail per fact**

Use when you need richer facts with full context, relationships, and verbosity. Slower and uses more tokens than `concise`.

**`ATULYA_API_RETAIN_EXTRACTION_MODE=custom` + `ATULYA_API_RETAIN_CUSTOM_INSTRUCTIONS` — full control**

Replaces the built-in selectivity rules entirely. The structural parts of the prompt (output format, temporal handling, coreference resolution) remain intact — only the extraction guidelines are replaced.

Use this when `retain_mission` isn't sufficient and you need strict inclusion/exclusion logic.

```bash
export ATULYA_API_RETAIN_EXTRACTION_MODE=custom
export ATULYA_API_RETAIN_CUSTOM_INSTRUCTIONS="ONLY extract facts that are:
✅ Technical decisions and their rationale
✅ Architecture patterns and design choices
✅ Performance metrics and benchmarks

DO NOT extract:
❌ Greetings or social conversation
❌ Process chatter (\"let me check\", \"one moment\")
❌ Anything that would not be useful in 6 months"
```

### File Processing

Configuration for the file upload and conversion pipeline (used by `POST /v1/default/banks/{bank_id}/files/retain`).

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_ENABLE_FILE_UPLOAD_API` | Enable the file upload API endpoint | `true` |
| `ATULYA_API_FILE_PARSER` | Server-side default parser or fallback chain (comma-separated, e.g. `iris,markitdown`) | `markitdown` |
| `ATULYA_API_FILE_PARSER_ALLOWLIST` | Comma-separated list of parsers clients are allowed to request. If not set, all registered parsers are allowed. | — |
| `ATULYA_API_FILE_CONVERSION_MAX_BATCH_SIZE` | Max files per upload request | `10` |
| `ATULYA_API_FILE_CONVERSION_MAX_BATCH_SIZE_MB` | Max total upload size per request (MB) | `100` |
| `ATULYA_API_FILE_DELETE_AFTER_RETAIN` | Delete stored files after memory extraction completes | `true` |

#### Parser selection

Clients can override the server default by passing `parser` in the request body of `POST /v1/default/banks/{bank_id}/files/retain`. Both the server default and the per-request field accept a single parser name or an ordered **fallback chain** — each parser is tried in sequence until one succeeds.

```bash
# Server default: try iris first, fall back to markitdown if iris fails
export ATULYA_API_FILE_PARSER=iris,markitdown

# Restrict what clients may request (optional — defaults to all registered parsers)
export ATULYA_API_FILE_PARSER_ALLOWLIST=markitdown,iris
```

```json
// Per-request override (in the JSON body of the file retain endpoint)
{
  "parser": "iris",
  "files_metadata": [
    { "document_id": "report" },
    { "document_id": "fallback_doc", "parser": ["iris", "markitdown"] }
  ]
}
```

Clients that request a parser not in the allowlist receive HTTP 400.

#### Parser: markitdown (default)

Local file-to-markdown conversion using [Microsoft's markitdown](https://github.com/microsoft/markitdown). No external service required.

**Supported formats:** PDF, DOCX, DOC, PPTX, PPT, XLSX, XLS, images (JPG, PNG — OCR), audio (MP3, WAV — transcription), HTML, TXT, MD, CSV.

#### Parser: iris

Cloud-based extraction via [Vectorize Iris](https://docs.eightengine.com/build-deploy/extract-information/understanding-iris/). Higher quality extraction for complex documents, powered by a remote AI service.

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_FILE_PARSER_IRIS_TOKEN` | Vectorize API token | — |
| `ATULYA_API_FILE_PARSER_IRIS_ORG_ID` | Vectorize organization ID | — |

**Supported formats:** PDF, DOCX, DOC, PPTX, PPT, XLSX, XLS, images (JPG, JPEG, PNG, GIF, BMP, TIFF, WEBP), HTML, TXT, MD, CSV.

```bash
# Use iris as the only parser
export ATULYA_API_FILE_PARSER=iris
export ATULYA_API_FILE_PARSER_IRIS_TOKEN=your-vectorize-token
export ATULYA_API_FILE_PARSER_IRIS_ORG_ID=your-org-id

# Or: try iris first, fall back to markitdown if iris fails or rejects the file type
export ATULYA_API_FILE_PARSER=iris,markitdown
```

```bash
# Increase batch limits for large file imports
export ATULYA_API_FILE_CONVERSION_MAX_BATCH_SIZE=20
export ATULYA_API_FILE_CONVERSION_MAX_BATCH_SIZE_MB=500

# Keep files after processing (useful for debugging or re-processing)
export ATULYA_API_FILE_DELETE_AFTER_RETAIN=false
```

### File Storage

Files uploaded via the file retain API are stored in an object storage backend before conversion. Choose the backend that fits your infrastructure.

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_FILE_STORAGE_TYPE` | Storage backend: `native`, `s3`, `gcs`, or `azure` | `native` |

#### Native (PostgreSQL)

Files are stored as `BYTEA` in the `file_storage` table. No additional infrastructure required. Suitable for development and small deployments.

```bash
# Native storage is the default — no additional configuration needed
export ATULYA_API_FILE_STORAGE_TYPE=native
```

#### S3 / S3-Compatible

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_FILE_STORAGE_S3_BUCKET` | S3 bucket name | - |
| `ATULYA_API_FILE_STORAGE_S3_REGION` | AWS region | - |
| `ATULYA_API_FILE_STORAGE_S3_ENDPOINT` | Custom endpoint URL (for S3-compatible stores like MinIO, Cloudflare R2) | AWS default |
| `ATULYA_API_FILE_STORAGE_S3_ACCESS_KEY_ID` | AWS access key ID | - |
| `ATULYA_API_FILE_STORAGE_S3_SECRET_ACCESS_KEY` | AWS secret access key | - |

```bash
# AWS S3
export ATULYA_API_FILE_STORAGE_TYPE=s3
export ATULYA_API_FILE_STORAGE_S3_BUCKET=my-atulya-files
export ATULYA_API_FILE_STORAGE_S3_REGION=us-east-1
export ATULYA_API_FILE_STORAGE_S3_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
export ATULYA_API_FILE_STORAGE_S3_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY

# S3-compatible (MinIO, Cloudflare R2, etc.)
export ATULYA_API_FILE_STORAGE_TYPE=s3
export ATULYA_API_FILE_STORAGE_S3_BUCKET=my-bucket
export ATULYA_API_FILE_STORAGE_S3_ENDPOINT=https://your-minio.example.com
export ATULYA_API_FILE_STORAGE_S3_ACCESS_KEY_ID=minioadmin
export ATULYA_API_FILE_STORAGE_S3_SECRET_ACCESS_KEY=minioadmin
```

#### Google Cloud Storage

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_FILE_STORAGE_GCS_BUCKET` | GCS bucket name | - |
| `ATULYA_API_FILE_STORAGE_GCS_SERVICE_ACCOUNT_KEY` | Path to service account JSON key file | ADC if not set |

```bash
export ATULYA_API_FILE_STORAGE_TYPE=gcs
export ATULYA_API_FILE_STORAGE_GCS_BUCKET=my-atulya-files
# Optional: use service account key file (otherwise falls back to ADC)
export ATULYA_API_FILE_STORAGE_GCS_SERVICE_ACCOUNT_KEY=/path/to/key.json
```

#### Azure Blob Storage

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_FILE_STORAGE_AZURE_CONTAINER` | Azure container name | - |
| `ATULYA_API_FILE_STORAGE_AZURE_ACCOUNT_NAME` | Azure storage account name | - |
| `ATULYA_API_FILE_STORAGE_AZURE_ACCOUNT_KEY` | Azure storage account key | - |

```bash
export ATULYA_API_FILE_STORAGE_TYPE=azure
export ATULYA_API_FILE_STORAGE_AZURE_CONTAINER=atulya-files
export ATULYA_API_FILE_STORAGE_AZURE_ACCOUNT_NAME=mystorageaccount
export ATULYA_API_FILE_STORAGE_AZURE_ACCOUNT_KEY=base64encodedkey==
```

#### Storage Backend Comparison

| Backend | Best For | Notes |
|---------|----------|-------|
| `native` | Development, small deployments | No extra infrastructure, stored in PostgreSQL |
| `s3` | Production, AWS deployments | Works with any S3-compatible store |
| `gcs` | Production, GCP deployments | Supports ADC for keyless auth |
| `azure` | Production, Azure deployments | Uses account key auth |

:::tip Production Recommendation
For production deployments, use `s3`, `gcs`, or `azure` to avoid storing large binary files in your PostgreSQL database. Set `ATULYA_API_FILE_DELETE_AFTER_RETAIN=true` (the default) to delete files after memory extraction, which minimizes storage costs.
:::

### Observations (Experimental) {#observations}

Observations are consolidated knowledge synthesized from facts.

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_ENABLE_OBSERVATIONS` | Enable observation consolidation | `true` |
| `ATULYA_API_ENABLE_OBSERVATION_HISTORY` | Track history of changes to each observation (previous content + timestamp). Disable to reduce storage if audit trails are not needed. | `true` |
| `ATULYA_API_CONSOLIDATION_BATCH_SIZE` | Memories to load per batch (internal optimization) | `50` |
| `ATULYA_API_CONSOLIDATION_MAX_TOKENS` | Max tokens for recall when finding related observations during consolidation | `1024` |
| `ATULYA_API_CONSOLIDATION_LLM_BATCH_SIZE` | Number of facts sent to the LLM in a single consolidation call. Higher values reduce LLM calls and improve throughput at the cost of larger prompts. Set to `1` to disable batching. Configurable per bank. | `8` |
| `ATULYA_API_CONSOLIDATION_SOURCE_FACTS_MAX_TOKENS` | Total token budget for source facts included with observations in the consolidation prompt. `-1` = unlimited. Configurable per bank. | `-1` |
| `ATULYA_API_CONSOLIDATION_SOURCE_FACTS_MAX_TOKENS_PER_OBSERVATION` | Per-observation token cap for source facts in the consolidation prompt. Each observation independently gets at most this many tokens of source facts. `-1` = unlimited. Configurable per bank. | `256` |
| `ATULYA_API_OBSERVATIONS_MISSION` | What this bank should synthesise into durable observations. Replaces the built-in consolidation rules — leave unset to use the server default. | - |

#### Customizing observations: when to use what

| Goal | Use |
|------|-----|
| Default behavior: durable specific facts, no ephemeral state | Leave unset |
| Change what observations *are* for this bank (different shape, different purpose) | `ATULYA_API_OBSERVATIONS_MISSION` |

**`ATULYA_API_OBSERVATIONS_MISSION` — redefine what this bank synthesises**

By default, observations are durable, specific facts synthesized from memories — the kind of knowledge that stays true over time (preferences, skills, relationships, recurring patterns). Ephemeral state is filtered out. Contradictions are tracked with temporal markers.

Set `ATULYA_API_OBSERVATIONS_MISSION` to replace this definition entirely. Write a plain-language description of what observations should be for your use case. The LLM will use this instead of the default rules when deciding what to create or update. Leave it unset to keep the server default.

:::tip When to use observations_mission
Use it when the default durable-knowledge behavior doesn't match your use case. Common scenarios:
- You want **broader event summaries** rather than isolated facts
- You want observations **grouped by time period** (weekly, monthly)
- You want a **different granularity** (one observation per project rather than per fact)
- You have a **domain-specific** notion of what's worth remembering
:::

**Example: Weekly event summaries**

```bash
export ATULYA_API_OBSERVATIONS_MISSION="Observations are broad summaries of project events grouped by week. Each observation should capture what happened, what was decided, and what was blocked — not individual facts. Merge related events into cohesive weekly narratives."
```

**Example: Person-centric knowledge**

```bash
export ATULYA_API_OBSERVATIONS_MISSION="Observations are durable facts about specific named people: their preferences, skills, relationships, and behavioral patterns. Only create observations for facts that are stable over time and tied to a named individual."
```

**Example: Support ticket patterns**

```bash
export ATULYA_API_OBSERVATIONS_MISSION="Observations are recurring patterns in customer support interactions: common failure modes, frequently requested features, and pain points that appear across multiple tickets."
```

### Reflect

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_REFLECT_MAX_ITERATIONS` | Max tool call iterations before forcing a response | `10` |
| `ATULYA_API_REFLECT_MAX_CONTEXT_TOKENS` | Max accumulated context tokens in the reflect loop before forcing final synthesis. Prevents `context_length_exceeded` errors on large banks. Lower this if your LLM has a context window smaller than 128K. | `100000` |
| `ATULYA_API_REFLECT_MISSION` | Global reflect mission (identity and reasoning framing). Overridden per bank via config API. | - |

### Dream/Trance (Bank Config)

Dream/Trance is configured per bank under the `dream` object (via bank config API), not via a single global env toggle.

High-signal fields in `dream`:

- `enabled`, `trance_enabled`
- `trigger_mode` (`event`, `cron`, `hybrid`)
- `cron_interval_minutes`, `cooldown_minutes`
- `top_k`, `min_recall_results`
- `max_input_tokens`, `max_output_tokens`
- `quality_threshold`
- `distillation_mode` (`off`, `summary`, `fragments`)
- `distillation_max_fragments`
- `language_tone`, `enforce_layman`
- `value_focus` (`money`, `time`, `happiness`)
- `preset` (`balanced_org`, `lean_local`, `risk_guard`, `exec_strategy`)

### Brain Intelligence Analytics

Use the influence endpoint for visual analytics in the control plane and custom dashboards.

| Endpoint query | Description | Default |
|----------------|-------------|---------|
| `window_days` | Analytics lookback window | `14` |
| `top_k` | Number of leaderboard entities | `12` |
| `entity_type` | Filter: `all`, `memory`, `chunk`, `mental_model` | `all` |

Math behaviors:

- Influence score decomposition: `recency + freq + graph + rerank + dream`
- EWMA trend smoothing for stable directionality
- Robust anomaly detection using z-score + IQR
- Confidence bands (`lower`, `upper`) returned per trend point

#### Disposition

Disposition traits control how the bank reasons during reflect operations. Each trait is on a scale of 1–5. These are hierarchical — they can be overridden per bank via the [config API](./configuration.md#hierarchical-configuration).

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_DISPOSITION_SKEPTICISM` | How skeptical vs trusting (1=trusting, 5=skeptical) | `3` |
| `ATULYA_API_DISPOSITION_LITERALISM` | How literally to interpret information (1=flexible, 5=literal) | `3` |
| `ATULYA_API_DISPOSITION_EMPATHY` | How much to consider emotional context (1=detached, 5=empathetic) | `3` |

### MCP Server

Configuration for MCP server endpoints.

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_MCP_ENABLED` | Enable MCP server at `/mcp/{bank_id}/` | `true` |
| `ATULYA_API_MCP_ENABLED_TOOLS` | Comma-separated allowlist of MCP tools to expose globally (empty = all tools) | - |
| `ATULYA_API_MCP_AUTH_TOKEN` | Bearer token for MCP authentication (optional) | - |
| `ATULYA_API_MCP_LOCAL_BANK_ID` | Memory bank ID for local MCP | `mcp` |
| `ATULYA_API_MCP_INSTRUCTIONS` | Additional instructions appended to retain/recall tool descriptions | - |

**Tool Access Control:**

`ATULYA_API_MCP_ENABLED_TOOLS` restricts which MCP tools are registered at the server level. This is useful for read-only deployments or limiting surface area:

```bash
# Expose only recall (read-only deployment)
export ATULYA_API_MCP_ENABLED_TOOLS=recall

# Expose recall and reflect only
export ATULYA_API_MCP_ENABLED_TOOLS=recall,reflect
```

Available tool names: `retain`, `recall`, `reflect`, `list_banks`, `create_bank`, `list_mental_models`, `get_mental_model`, `create_mental_model`, `update_mental_model`, `delete_mental_model`, `refresh_mental_model`, `list_directives`, `create_directive`, `delete_directive`, `list_memories`, `get_memory`, `delete_memory`, `list_documents`, `get_document`, `delete_document`, `list_operations`, `get_operation`, `cancel_operation`, `list_tags`, `get_bank`, `get_bank_stats`, `update_bank`, `delete_bank`, `clear_memories`.

This can also be overridden per bank via the [config API](#hierarchical-configuration):

```bash
# Restrict a specific bank to read-only MCP access
curl -X PATCH http://localhost:8888/v1/default/banks/my-bank/config \
  -H "Content-Type: application/json" \
  -d '{"updates": {"mcp_enabled_tools": ["recall"]}}'
```

When a bank-level `mcp_enabled_tools` is set, tools not in the list return a clear error when invoked (they still appear in the tools list for MCP protocol compatibility).

**MCP Authentication:**

By default, the MCP endpoint is open. For production deployments, set `ATULYA_API_MCP_AUTH_TOKEN` to require Bearer token authentication:

```bash
export ATULYA_API_MCP_AUTH_TOKEN=your-secret-token
```

Clients must then include the token in the `Authorization` header. See [MCP Server documentation](./mcp-server.md#authentication) for details.

**Local MCP instructions:**

```bash
# Example: instruct MCP to also store assistant actions
export ATULYA_API_MCP_INSTRUCTIONS="Also store every action you take, including tool calls and decisions made."
```

### Distributed Workers

Configuration for background task processing. By default, the API processes tasks internally. For high-throughput deployments, run dedicated workers. See [Services - Worker Service](./services#worker-service) for details.

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_WORKER_ENABLED` | Enable internal worker in API process | `true` |
| `ATULYA_API_WORKER_ID` | Unique worker identifier | hostname |
| `ATULYA_API_WORKER_POLL_INTERVAL_MS` | Database polling interval in milliseconds | `500` |
| `ATULYA_API_WORKER_MAX_RETRIES` | Max retries before marking task failed | `3` |
| `ATULYA_API_WORKER_HTTP_PORT` | HTTP port for worker metrics/health (worker CLI only) | `8889` |
| `ATULYA_API_WORKER_MAX_SLOTS` | Maximum concurrent tasks per worker | `10` |
| `ATULYA_API_WORKER_CONSOLIDATION_MAX_SLOTS` | Maximum concurrent consolidation tasks per worker | `2` |

### Performance Optimization

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_SKIP_LLM_VERIFICATION` | Skip LLM connection check on startup | `false` |
| `ATULYA_API_LAZY_RERANKER` | Lazy-load reranker model (faster startup) | `false` |

### Programmatic Configuration

You can also configure the API programmatically using `MemoryEngine.from_env()`:

```python
from atulya_api import MemoryEngine

memory = MemoryEngine.from_env()
await memory.initialize()
```

---

## Observability & Tracing

Atulya provides OpenTelemetry-based observability for LLM calls, conforming to GenAI semantic conventions.

### OpenTelemetry Tracing

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_OTEL_TRACES_ENABLED` | Enable distributed tracing for LLM calls | `false` |
| `ATULYA_API_OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint URL (e.g., Grafana LGTM, Langfuse, etc.) | - |
| `ATULYA_API_OTEL_EXPORTER_OTLP_HEADERS` | Headers for OTLP exporter (format: "key1=value1,key2=value2") | - |
| `ATULYA_API_OTEL_SERVICE_NAME` | Service name for traces | `atulya-api` |
| `ATULYA_API_OTEL_DEPLOYMENT_ENVIRONMENT` | Deployment environment name (e.g., development, staging, production) | `development` |

**Features:**
- Full prompts and completions recorded as events
- Token usage tracking (input/output)
- Model and provider information
- Error tracking with finish reasons
- Conforms to OpenTelemetry GenAI semantic conventions v1.37+

**OTLP-Compatible Backends:**

The tracing implementation uses standard OTLP HTTP protocol, so it works with any OTLP-compatible backend:
- **Grafana LGTM** (Recommended for local dev): All-in-one stack with Tempo traces, Loki logs, Mimir metrics, and Grafana UI
- **Langfuse**: LLM-focused observability and analytics
- **OpenLIT**: Built-in LLM dashboards, cost tracking
- **DataDog, New Relic, Honeycomb**: Commercial platforms

**Example Configuration:**

```bash
# Enable tracing
export ATULYA_API_OTEL_TRACES_ENABLED=true

# Configure endpoint (example: OpenLIT Cloud)
export ATULYA_API_OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp.openlit.io
export ATULYA_API_OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer olit-xxx"

# Optional: Custom service name and environment
export ATULYA_API_OTEL_SERVICE_NAME=atulya-production
export ATULYA_API_OTEL_DEPLOYMENT_ENVIRONMENT=production
```

**Local Development:**

For local development, we recommend the Grafana LGTM stack which provides traces, metrics, and logs in a single container:

```bash
./scripts/dev/start-grafana.sh
```

See `scripts/dev/grafana/README.md` for detailed setup instructions.

Other options: See `scripts/dev/openlit/README.md` for OpenLIT or `scripts/dev/jaeger/README.md` for standalone Jaeger.

### Metrics

Atulya exposes Prometheus metrics at the `/metrics` endpoint, including:
- LLM call duration and token usage
- Operation duration (retain/recall/reflect)
- HTTP request metrics
- Database connection pool metrics

Metrics are always enabled and available at `http://localhost:8888/metrics`.

---

## Control Plane

The Control Plane is the web UI for managing memory banks.

It now includes Graph Intelligence for:

- seeing what changed in a bank
- investigating why Atulya believes something
- drilling from state into raw supporting memories

See [Control Plane Graph Intelligence](./control-plane-graph-intelligence) for the product workflow.

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_CP_DATAPLANE_API_URL` | URL of the API service | `http://localhost:8888` |
| `NEXT_PUBLIC_BASE_PATH` | Base path for Control Plane UI when behind reverse proxy (e.g., `/atulya`) | `""` (root) |

```bash
# Point Control Plane to a remote API service
export ATULYA_CP_DATAPLANE_API_URL=http://api.example.com:8888
```

### Hierarchical Configuration

Atulya supports per-bank configuration overrides through a hierarchical system: **Global (env vars) → Tenant → Bank**.

**Bank presets** (`bank_preset` on `PUT` / `PATCH` `/v1/default/banks/{bank_id}`) merge a curated default bundle (for example `codebase`) before any explicit fields you send. See [Bank presets](/developer/bank-presets).

#### Type-Safe Config Access

To prevent accidentally using global defaults when bank-specific overrides exist, Atulya enforces type-safe config access:

**In Application Code:**
```python
from atulya_api.config import get_config

# ✅ Access static (infrastructure) fields
config = get_config()
host = config.host  # OK - static field
port = config.port  # OK - static field

# ❌ Attempting to access bank-configurable fields raises an error
chunk_size = config.retain_chunk_size  # ConfigFieldAccessError!
```

**Error Message:**
```
ConfigFieldAccessError: Field 'retain_chunk_size' is bank-configurable and cannot
be accessed from global config. Use ConfigResolver.resolve_full_config(bank_id, context)
to get bank-specific config.
```

**For Bank-Specific Config:**
```python
# Internal code that needs bank-specific settings
from atulya_api.config_resolver import ConfigResolver

# Resolve full config for a specific bank
config = await config_resolver.resolve_full_config(bank_id, request_context)
chunk_size = config.retain_chunk_size  # ✅ Uses bank-specific value
```

This design prevents bugs where global defaults are used instead of bank overrides, making it impossible to make this mistake at compile/development time.

#### Security Model

Configuration fields are categorized for security:

1. **Configurable Fields** - Safe behavioral settings that can be customized per-bank:
   - Retention: `retain_chunk_size`, `retain_extraction_mode`, `retain_mission`, `retain_custom_instructions`
   - Observations: `enable_observations`, `observations_mission`
   - MCP access control: `mcp_enabled_tools`

2. **Credential Fields** - NEVER exposed or configurable via API:
   - API keys: `*_api_key` (all LLM API keys)
   - Infrastructure: `*_base_url` (all base URLs)

3. **Static Fields** - Server-level only, cannot be overridden:
   - Infrastructure: `database_url`, `port`, `host`, `worker_count`
   - Provider/Model selection: `llm_provider`, `llm_model` (requires presets - not yet implemented)
   - Performance tuning: `llm_max_concurrent`, `llm_timeout`, retrieval settings, optimization flags

#### Enabling the API

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_ENABLE_BANK_CONFIG_API` | Enable per-bank config API | `true` |

#### API Endpoints

- `GET /v1/default/banks/{bank_id}/config` - View resolved config (filtered by permissions)
- `PATCH /v1/default/banks/{bank_id}/config` - Update bank overrides (only allowed fields)
- `DELETE /v1/default/banks/{bank_id}/config` - Reset to defaults

#### Permission System

Tenant extensions can control which fields banks are allowed to modify via `get_allowed_config_fields()`:

```python
class CustomTenantExtension(TenantExtension):
    async def get_allowed_config_fields(self, context, bank_id):
        # Option 1: Allow all configurable fields
        return None

        # Option 2: Allow specific fields only
        return {"retain_chunk_size", "retain_custom_instructions"}

        # Option 3: Read-only (no modifications)
        return set()
```

#### Examples

```bash
# Update retention settings for a bank
curl -X PATCH http://localhost:8888/v1/default/banks/my-bank/config \
  -H "Content-Type: application/json" \
  -d '{
    "updates": {
      "retain_chunk_size": 4000,
      "retain_extraction_mode": "custom",
      "retain_custom_instructions": "Focus on technical details and implementation specifics"
    }
  }'

# Note: retain_extraction_mode must be "custom" to use retain_custom_instructions

# View resolved config (respects permissions)
curl http://localhost:8888/v1/default/banks/my-bank/config

# Reset to defaults
curl -X DELETE http://localhost:8888/v1/default/banks/my-bank/config
```

**Security Notes:**
- Credentials (API keys, base URLs) are never returned in responses
- Only configurable fields can be modified
- Responses are filtered by tenant permissions
- Attempting to set credentials returns 400 error

### Reverse Proxy / Subpath Deployment

To deploy Atulya under a subpath (e.g., `example.com/atulya/`):

1. Set both environment variables to the same path:
   ```bash
   ATULYA_API_BASE_PATH=/atulya
   NEXT_PUBLIC_BASE_PATH=/atulya
   ```

2. Configure your reverse proxy to:
   - Forward `/atulya/*` requests to Atulya
   - Preserve the full path in forwarded requests
   - Set appropriate proxy headers (X-Forwarded-Proto, X-Forwarded-For)

**Example: Nginx Configuration**

```nginx
location /atulya/ {
    proxy_pass http://localhost:8888/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

**Example: Traefik Configuration**

```yaml
http:
  routers:
    atulya:
      rule: "PathPrefix(`/atulya`)"
      service: atulya
      middlewares:
        - atulya-stripprefix

  middlewares:
    atulya-stripprefix:
      stripPrefix:
        prefixes:
          - "/atulya"

  services:
    atulya:
      loadBalancer:
        servers:
          - url: "http://localhost:8888"
```

**Important Notes:**
- The base path must start with `/` and should NOT end with `/`
- Both API and Control Plane should use the same base path
- After setting environment variables, restart both services
- OpenAPI docs will be available at `<base-path>/docs` (e.g., `/atulya/docs`)

**Complete Examples:**

See `docker/compose-examples/` directory for:
- Nginx configuration files (`simple.conf`, `api-and-control-plane.conf`)
- Docker Compose setups (`docker-compose.yml`, `reverse-proxy-only.yml`)
- Traefik and other reverse proxy examples
- Full deployment documentation
---

## Example .env File

```bash
# API Service
ATULYA_API_DATABASE_URL=postgresql://atulya:atulya_dev@localhost:5432/atulya
# ATULYA_API_DATABASE_SCHEMA=public  # optional, defaults to 'public'
ATULYA_API_LLM_PROVIDER=groq
ATULYA_API_LLM_API_KEY=gsk_xxxxxxxxxxxx

# Authentication (optional, recommended for production)
# ATULYA_API_TENANT_EXTENSION=atulya_api.extensions.builtin.tenant:ApiKeyTenantExtension
# ATULYA_API_TENANT_API_KEY=your-secret-api-key

# File storage (optional, defaults to PostgreSQL native storage)
# ATULYA_API_FILE_STORAGE_TYPE=s3
# ATULYA_API_FILE_STORAGE_S3_BUCKET=my-atulya-files
# ATULYA_API_FILE_STORAGE_S3_REGION=us-east-1
# ATULYA_API_FILE_STORAGE_S3_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
# ATULYA_API_FILE_STORAGE_S3_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY

# Control Plane
ATULYA_CP_DATAPLANE_API_URL=http://localhost:8888
```

---

For configuration issues not covered here, please [open an issue](https://github.com/eight-atulya/atulya/issues) on GitHub.
