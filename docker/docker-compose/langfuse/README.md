# Langfuse (self-hosted) for Atulya OTEL

Docker Compose stack for [Langfuse](https://langfuse.com/) aligned with the upstream [docker-compose.yml](https://github.com/langfuse/langfuse/blob/main/docker-compose.yml). Atulya sends OpenTelemetry traces to Langfuse’s HTTP OTLP endpoint (`/api/public/otel`; see [Langfuse OTEL docs](https://langfuse.com/docs/opentelemetry/example-opentelemetry-collector)).

This layout lives under **`docker/docker-compose/langfuse/`**, consistent with other stacks such as [`timescale`](../timescale/README.md) and [`vchord`](../vchord/docker-compose.yaml).

## Prerequisites

- Docker with Compose v2
- Shared external network **`atulya-network`** (same as `scripts/dev/monitoring`). Create if missing:

```bash
docker network create atulya-network
```

## Quick start

From the **Atulya repo root** (directory that contains `docker/` and `atulya-api/`):

```bash
./docker/docker-compose/langfuse/start.sh
```

Or explicitly:

```bash
docker compose -f docker/docker-compose/langfuse/docker-compose.yaml up -d
```

- **Langfuse UI**: http://localhost:3001 (port **3001** so it does not collide with Grafana LGTM on **3000**)
- **MinIO** (S3 API): http://localhost:9090
- **Langfuse Postgres (host only)**: `127.0.0.1:15432` → container `5432`. Langfuse services use `postgres:5432` inside Docker; this mapping is only if you need `psql` from the host. **15432** is used so this stack does not bind **5432** (Atulya embedded / dev Postgres).

Wait until `langfuse-web` logs show Ready (~2–3 minutes on first boot).

## Secrets

Before any non-local use, replace defaults for `SALT`, `ENCRYPTION_KEY`, `NEXTAUTH_SECRET`, `POSTGRES_PASSWORD`, `CLICKHOUSE_PASSWORD`, `REDIS_AUTH`, MinIO credentials, and Langfuse S3-related secrets (see upstream compose comments). Generate `ENCRYPTION_KEY` with `openssl rand -hex 32`.

## Atulya environment

Create a Langfuse project in the UI and copy **public** and **secret** keys. Set:

```bash
ATULYA_API_OTEL_TRACES_ENABLED=true
ATULYA_API_OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:3001/api/public/otel
ATULYA_API_OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic <AUTH_B64>,x-langfuse-ingestion-version=4"
```

Build `AUTH_B64`:

```bash
echo -n 'pk-lf-...:sk-lf-...' | base64
# GNU: add -w 0 to avoid line wrapping
```

Use **OTLP over HTTP** only; Langfuse does not accept gRPC on this path. Postgres and ClickHouse must use **UTC** (already set in this compose).

## Grafana LGTM

If you run the [dev monitoring stack](../../../scripts/dev/monitoring/README.md) (Grafana LGTM), keep Grafana on **3000** and Langfuse on **3001**.

## Troubleshooting

- Images are pinned to **3.172.1** (web + worker). Older pins (for example **3.22.x**) could return **500** on `POST /api/public/otel/v1/traces` with server logs like `RangeError: Invalid time value` when mapping OTLP spans. After bumping the tag, run `docker compose -f docker/docker-compose/langfuse/docker-compose.yaml pull && docker compose -f docker/docker-compose/langfuse/docker-compose.yaml up -d`.
- Traces missing after self-host upgrade: see Langfuse [self-host troubleshooting](https://langfuse.com/self-hosting/troubleshooting-and-faq) and [issue #8424](https://github.com/langfuse/langfuse/issues/8424) class reports for OTLP edge cases.
- Stop: `docker compose -f docker/docker-compose/langfuse/docker-compose.yaml down` (add `-v` to drop volumes).

## Convenience wrapper

From repo root you can also run:

```bash
./scripts/dev/start-langfuse.sh
```

That delegates to `docker/docker-compose/langfuse/start.sh`.
