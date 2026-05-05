# Services

Atulya consists of three services that can run together or separately depending on your deployment needs.

## API Service

The core memory engine. Handles all memory operations:

- **Retain**: Ingests content, extracts facts, builds knowledge graph
- **Recall**: Semantic search across memories
- **Reflect**: Disposition-aware answer generation

```bash
atulya-api        # Default port: 8888
```

The API service is stateless and can be horizontally scaled behind a load balancer. All state is stored in PostgreSQL.

By default, the API also processes background tasks (mental model consolidation) internally. For high-throughput deployments, you can disable this and run dedicated workers instead.

## Worker Service

Dedicated task processor for background operations. Uses the **same package and Docker image** as the API service, just with a different entry point.

```bash
atulya-worker     # Default metrics port: 8889
```

Workers use PostgreSQL as a task broker, polling for pending tasks. Multiple workers can run simultaneously without conflicts.

| Deployment | Internal Worker | Dedicated Workers |
|------------|-----------------|-------------------|
| **Development** | ✅ Simple, all-in-one | ❌ Overkill |
| **Small production** | ✅ Less infrastructure | ❌ Overkill |
| **High throughput** | ❌ API bottleneck | ✅ Scale independently |
| **Long-running tasks** | ❌ Blocks API resources | ✅ Isolated processing |

To use dedicated workers, disable the internal worker in the API and start worker processes:

```bash
# Disable internal worker in API
ATULYA_API_WORKER_ENABLED=false atulya-api

# Start dedicated workers (run multiple instances)
atulya-worker --worker-id worker-1
atulya-worker --worker-id worker-2
```

Each worker exposes `/health` and `/metrics` endpoints for monitoring.

Before scaling down or removing workers, release their tasks with `atulya-admin decommission-worker <worker-id>`.

See [Configuration - Distributed Workers](./configuration#distributed-workers) for all worker settings and [Installation - Helm](./installation#distributed-workers) for Kubernetes deployment.

## Control Plane

Web UI for managing and exploring your memory banks:

- Browse agents and memory banks
- See what changed in a bank with **State Graph**
- Inspect supporting raw memories with **Evidence Graph**
- Move from summary to proof with graph-backed investigation
- View ingestion history and operations

The Control Plane connects to the API service and provides a visual interface for development and debugging.

For a deeper walkthrough of the new graph workflow, see [Control Plane Graph Intelligence](./control-plane-graph-intelligence).

For bare metal deployments, you can run the Control Plane standalone using npx. See [Installation - Bare Metal](./installation#control-plane) for details.

## Optional Internet Stack

Internet Research uses an optional connector stack instead of expanding the core API/worker responsibilities:

- **SearXNG** for compact public-web metasearch
- **Firecrawl** for URL-to-markdown extraction

These connectors are optional on purpose:

- the core Atulya memory system still runs without them
- internet research can be enabled per deployment when operators need live-web evidence
- the research flow stays explicitly separate from Retain until a human chooses to promote curated material

For the end-to-end workflow, see [Internet Research](./internet-research). For the exact environment variables, see [Configuration - Internet Research Stack](./configuration#internet-research-stack).
