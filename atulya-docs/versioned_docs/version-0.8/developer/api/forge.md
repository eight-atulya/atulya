---
sidebar_position: 10
---

# Forge API

Create training datasets from a memory bank: submit forge jobs, preview Atulya Training Records (ATR), export JSONL.

:::tip Overview
For concepts, recipes, and ROI, read [**Data Forge**](../data-forge) first.
:::

All endpoints are scoped to a single bank: `/v1/default/banks/{bank_id}/forge/...`

---

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/forge/recipes` | List recipes, exporters, domain profiles, stages |
| `POST` | `/forge/jobs` | Start async forge job |
| `GET` | `/forge/records` | Paginated ATR preview |
| `POST` | `/forge/export` | Export via adapter (JSONL in response body) |
| `GET` | `/forge/jobs/{operation_id}/lineage` | Lineage manifest for a completed job |

Forge jobs are **async operations**. Poll status with [Operations](./operations):

- `GET /operations/{operation_id}`
- `GET /operations/{operation_id}/result` — includes `quality_summary` on completion

---

## List recipes

```bash
curl "http://localhost:8000/v1/default/banks/my-bank/forge/recipes?domain_tags=startup_ops"
```

Response shape:

```json
{
  "recipes": [
    {
      "recipe_id": "temporal_qa",
      "version": "1",
      "title": "Temporal Q&A",
      "description": "Multi-hop questions with recall + reflect and cited memory IDs.",
      "requires_ingest": false,
      "cost_tier": "medium",
      "training_signal": "Temporal reasoning with citations"
    }
  ],
  "exporters": [
    {
      "adapter_id": "atr_jsonl",
      "version": "1",
      "title": "ATR JSONL",
      "description": "Canonical Atulya Training Record format."
    }
  ],
  "domain_profiles": [
    {
      "id": "startup_ops",
      "title": "Startup ops",
      "description": "Customer calls, deals, incidents, product decisions."
    }
  ],
  "suggested_recipes": ["agent_trace", "temporal_qa", "consolidation_pairs"],
  "stages": [
    { "id": "ingest", "label": "Ingesting source" }
  ]
}
```

---

## Submit forge job

```bash
curl -X POST "http://localhost:8000/v1/default/banks/my-bank/forge/jobs" \
  -H "Content-Type: application/json" \
  -d '{
    "recipe_id": "consolidation_pairs",
    "domain_tags": ["startup_ops"],
    "quality_threshold": 0.6,
    "wait_consolidation": true,
    "repo_commit_on_complete": false,
    "source": {
      "source_type": "scenario",
      "payload": {
        "scenarios": [
          {
            "id": "deploy-1",
            "facts": [
              {
                "id": "f1",
                "key": "deploy_region",
                "value": "us-east-1",
                "timestamp": "2026-01-05T09:00:00Z"
              }
            ]
          }
        ]
      }
    }
  }'
```

### Request body

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `recipe_id` | string | required | Recipe from catalog |
| `domain_tags` | string[] | `[]` | Domain profile hints |
| `source` | object | optional | Ingest source; omit for bank-only recipes |
| `quality_threshold` | float | `0.6` | Minimum score for `exportable` |
| `wait_consolidation` | bool | `true` | Wait for consolidation before recipe |
| `max_records` | int | optional | Cap rows per job |
| `repo_commit_on_complete` | bool | `false` | Snapshot dataset to memory repo |
| `commit_message` | string | optional | Repo commit message |
| `options` | object | optional | Recipe-specific (e.g. `scenario_payload` for `synthetic_expand`) |

### Source object

| Field | Description |
|-------|-------------|
| `source_type` | `scenario` \| `chat` \| `timeseries` \| `bank_only` |
| `payload` | Adapter-specific JSON (empty for `bank_only`) |

Response:

```json
{
  "operation_id": "550e8400-e29b-41d4-a716-446655440000",
  "deduplicated": false
}
```

### Validation errors

Invalid requests return **400** with structured detail:

```json
{
  "detail": {
    "error": "forge_validation_error",
    "field": "source.payload.scenarios",
    "message": "Scenario source has no ingestible facts."
  }
}
```

---

## List forge records

```bash
curl "http://localhost:8000/v1/default/banks/my-bank/forge/records?operation_id=550e8400-e29b-41d4-a716-446655440000&limit=50"
```

| Query param | Description |
|-------------|-------------|
| `operation_id` | Filter to one forge job |
| `limit` / `offset` | Pagination |

Response:

```json
{
  "records": [
    {
      "record_id": "atr-abc123",
      "recipe_id": "temporal_qa",
      "quality_score": 0.85,
      "exportable": true,
      "record": { }
    }
  ],
  "total": 12,
  "exportable_total": 10,
  "limit": 50,
  "offset": 0
}
```

---

## Export

```bash
curl -X POST "http://localhost:8000/v1/default/banks/my-bank/forge/export" \
  -H "Content-Type: application/json" \
  -d '{
    "operation_id": "550e8400-e29b-41d4-a716-446655440000",
    "adapter_id": "openai_chat_jsonl",
    "quality_threshold": 0.6
  }'
```

| Field | Description |
|-------|-------------|
| `operation_id` | Completed forge job |
| `adapter_id` | `atr_jsonl` \| `openai_chat_jsonl` \| `graph_intelligence_jsonl` |
| `quality_threshold` | Override threshold at export time |
| `options` | Adapter-specific options |

Response includes `content` (JSONL string), `record_count`, `exportable_count`, and `quality_summary`.

Export errors (no records, threshold blocks all rows) return **400** with `forge_export_error`.

---

## Lineage

```bash
curl "http://localhost:8000/v1/default/banks/my-bank/forge/jobs/550e8400-e29b-41d4-a716-446655440000/lineage"
```

Returns recipe ID, bank ID, record counts, quality summary, and provenance metadata for audit trails.

---

## Operation result payload

When a forge job completes, `GET .../operations/{id}/result` includes:

```json
{
  "status": "completed",
  "operation_type": "forge_job",
  "result": {
    "quality_summary": {
      "total": 12,
      "exportable": 10,
      "held_back": 2,
      "pass_rate": 0.833,
      "avg_score": 0.78,
      "issue_counts": {
        "answer present without memory citations": 2
      }
    },
    "records_total": 12,
    "records_exportable": 10
  }
}
```

---

## Admin CLI

```bash
uv run atulya-admin forge run \
  --bank my-bank \
  --recipe consolidation_pairs \
  --source-file ./source.json \
  --domain-tag macro \
  --wait
```

See [Admin CLI](../admin-cli).
