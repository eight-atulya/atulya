---
sidebar_position: 7
---

# Development Guide

Guide to setting up a local development environment for contributing to Atulya.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) - Fast Python package manager
- Docker and Docker Compose
- An LLM API key (OpenAI, Groq, or Ollama)

## Local Development Setup

### 1. Clone the Repository

```bash
git clone https://github.com/eight-atulya/atulya.git
cd atulya
```

### 2. Install Dependencies

```bash
uv sync
```

### 3. Start PostgreSQL

Start only the database via Docker:

```bash
cd docker && docker-compose up -d postgres
```

### 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your LLM API key:

```bash
# Database (connects to Docker postgres)
ATULYA_API_DATABASE_URL=postgresql://atulya:atulya_dev@localhost:5432/atulya

# LLM Provider (choose one)
ATULYA_API_LLM_PROVIDER=groq
ATULYA_API_LLM_API_KEY=gsk_xxxxxxxxxxxx
ATULYA_API_LLM_MODEL=llama-3.1-70b-versatile
```

### 5. Start Services

Recommended local orchestrator (API + Control Plane):

```bash
./scripts/dev/start.sh
```

Optional startup modes:

```bash
# API only
./scripts/dev/start.sh --api-only

# Control Plane only
./scripts/dev/start.sh --cp-only

# API + Control Plane + worker
./scripts/dev/start.sh --with-worker

# Random free ports (avoids local port conflicts)
./scripts/dev/start.sh --random-port

# API + Control Plane with native atulya-brain auto-build (requires cargo)
./scripts/dev/start.sh --with-brain-native
```

If you only need the API:

```bash
./scripts/dev/start-api.sh
```

By default:
- API: `http://localhost:8888`
- Control Plane: `http://localhost:9999`

### Optional: native `atulya-brain` runtime

Rust is optional for core Atulya development. Use this only if you want native `atulya-brain` acceleration.

```bash
./scripts/dev/build-brain.sh
export ATULYA_API_BRAIN_ENABLED=true
export ATULYA_API_BRAIN_NATIVE_LIBRARY_PATH=/absolute/path/to/libatulya_brain.dylib
./scripts/dev/start-api.sh
```

## Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_retrieval.py

# Run with verbose output
uv run pytest -v
```

## Code Generation

### Regenerate API Clients

When you modify the OpenAPI spec, regenerate the clients:

```bash
./scripts/generate-clients.sh
```

This generates:
- Python client in `atulya-clients/python/`
- TypeScript client in `atulya-clients/typescript/`

### Export OpenAPI Schema

```bash
./scripts/export-openapi.sh
```

## Project Structure

```
atulya/
├── atulya-api/          # Main API server
│   ├── atulya_api/
│   │   ├── api/           # HTTP endpoints
│   │   ├── engine/        # Memory engine, retrieval, reasoning
│   │   └── web/           # Server entry point
│   └── tests/
├── atulya-clients/      # Generated SDK clients
│   ├── python/
│   └── typescript/
├── atulya-control-plane/ # Admin UI (Next.js)
├── docker/                 # Docker Compose setup
└── scripts/               # Development scripts
```

## Contributing

1. Create a feature branch from `main`
2. Make your changes
3. Run tests: `uv run pytest`
4. Submit a pull request

## Troubleshooting

### Database Connection Issues

Ensure PostgreSQL is running:

```bash
docker-compose ps
```

Check database connectivity:

```bash
psql postgresql://atulya:atulya_dev@localhost:5432/atulya
```

### ML Model Download

On first run, Atulya downloads embedding and reranking models. This may take a few minutes. Models are cached in `~/.cache/huggingface/`.

### Port Conflicts

If port 8888 is in use:

```bash
ATULYA_API_PORT=8889 ./scripts/dev/start-api.sh --port 8889
```

Or let the orchestrator select free ports:

```bash
./scripts/dev/start.sh --random-port
```
