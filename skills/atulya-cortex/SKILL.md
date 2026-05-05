---
name: atulya-cortex
description: >-
  Atulya Cortex (TUI/WhatsApp), Hand tools, internet stack (SearXNG/Firecrawl),
  config, and what-if troubleshooting. Use for cortex wiring, web_search/web_extract,
  deliberation limits, or docker internet-search compose.
---

# Atulya Cortex skill

## Stack health (internet tools)

From repo root (compose file path relative to `atulya/`):

```bash
docker ps --filter name=atulya-searxng --filter name=atulya-firecrawl-api
curl -sS -o /dev/null -w "searxng %{http_code}\n" http://127.0.0.1:18080/
curl -sS -o /dev/null -w "firecrawl %{http_code}\n" http://127.0.0.1:3002/v0/health/liveness
```

Expect **200** on both when the `internet-search` compose is up.

## Start TUI with `uv`

Repo root (`atulya/` workspace):

```bash
cd atulya-cortex
uv sync
uv run atulya-cortex
# same: uv run atulya-cortex chat
```

From monorepo root without `cd`:

```bash
uv run --directory atulya-cortex atulya-cortex
```

Dumb terminal / pipes: `uv run atulya-cortex chat --simple`.

## Enable internet tools (TUI = channel `tui`)

Edit cortex home `config.toml` (default `~/.atulya/cortex/` unless `ATULYA_CORTEX_HOME` / `--home`):

```toml
[tools]
enabled = true
allowed_channels = ["tui"]          # add "whatsapp" only if you trust that surface
max_actions = 4                     # search + extract + headroom for answer
internet_search_enabled = true
internet_extract_enabled = true
# Optional overrides (else env defaults):
# internet_searxng_base_url = "http://127.0.0.1:18080"
# internet_firecrawl_base_url = "http://127.0.0.1:3002"
# internet_firecrawl_api_key = "11111111-1111-4111-8111-111111111111"
```

Env (same names as `atulya-api`): `ATULYA_API_CORTEX_SEARXNG_BASE_URL`, `ATULYA_API_CORTEX_FIRECRAWL_API_URL`, `ATULYA_API_CORTEX_FIRECRAWL_API_KEY`. Put secrets in `<home>/.env`, not committed TOML.

Bring up stack: `docker compose -f docker/docker-compose/internet-search/docker-compose.yaml up -d` (from `atulya/`).

## How the model calls tools (XML tags)

One tag per turn, JSON body. Examples:

```text
<tool name="web_search">{"query": "IANA reserved IPv4 documentation prefix"}</tool>
```

Then (after digest):

```text
<tool name="web_extract">{"url": "https://www.iana.org/help/example-domains"}</tool>
```

Prefer **web_search → web_extract**; **web_fetch** only for tiny static HTML (raw markup burns context).

## What-if (short)

| Symptom | Check |
|--------|--------|
| Tool unknown / no `<tool_result>` | `[tools].enabled`, `max_actions`, model actually emitted valid JSON inside the tag |
| `web_search` errors | SearXNG up, JSON format allowed in `searxng/settings.yml` in compose, URL env |
| `web_extract` errors | Firecrawl liveness 200, Bearer UUID when self-hosted |
| No tools in prompt | `allowed_channels` must include channel root (`tui`, `whatsapp`, …) |
| `atulya_api` import warning | `atulya-cortex` needs `atulya-api` installed (workspace `uv sync`) |

## Why “search” looked dumb before

Small models often `bash curl` or `web_fetch` **Google SERP HTML** — useless. With `internet_search_enabled`, **web_search is listed first** in the tool catalogue, and **web_fetch is rejected** for common search-engine URLs with an error that points at `web_search`. Still set `internet_search_enabled=true` and run SearXNG.

## Token discipline (defaults)

- `web_search`: digest cap ~1100 chars; tune `internet_search_max_hits`, `internet_search_snippet_max_chars`.
- `web_extract`: default markdown cap 1200 chars; per-call `max_chars` in tool args or `internet_extract_max_chars` in config.
- System prompt adds an “internet discipline” block when those tools are registered—do not duplicate long prose elsewhere.

## Related paths

- Hand tools: `atulya-cortex/motors/fine_motor_skills.py`
- Wiring + `ToolSpec`s: `atulya-cortex/cortex/_runtime.py`
- HTTP client + compact payloads: `atulya-api/atulya_api/cortex/internet_connectors.py`
- Compose: `atulya/docker/docker-compose/internet-search/`
