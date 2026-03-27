---
sidebar_position: 9
---

# Operations

Background tasks that Atulya executes asynchronously.

:::tip Prerequisites
Make sure you've completed the [Quick Start](./quickstart) and understand [how retain works](./retain).
:::

## How Operations Work

Atulya processes several types of tasks in the background to maintain memory quality and consistency. These operations run automatically—you don't need to trigger them manually.

By default, all background operations are executed in-process within the API service.

:::note Kafka Integration
Support for external streaming platforms like Kafka for scale-out processing is planned but **not available out of the box** in the current release.
:::

## Operation Types

| Operation | Trigger | Description |
|-----------|---------|-------------|
| **batch_retain** | `retain_batch` with `async=True` | Processes large content batches in the background |
| **consolidate** | After `retain` | Consolidates new facts into observations |
| **dream_generation** | Consolidation events and/or cron (Dream config) | Runs Assumption -> Audit -> Train -> What-if -> Value synthesis and writes HTML artifacts |
| **sub_routine** | Manual trigger or startup warmup | Refreshes brain runtime cache and activity model |
| **brain_learn** | Manual trigger from control plane | Learns and fuses knowledge from a remote brain instance |

## Dream and Brain Intelligence Operations

`0.8.0` adds async intelligence workflows that are safe for production:

- **Dream/Trance generation** never blocks retain/recall paths.
- **LLM formatting failures** degrade gracefully via deterministic fallback behavior.
- **Brain analytics** are query-driven and bounded by request parameters (`window_days`, `top_k`, `entity_type`).

### Common intelligence endpoints

- `POST /v1/default/banks/{bank_id}/dreams/trigger`
- `GET /v1/default/banks/{bank_id}/dreams`
- `GET /v1/default/banks/{bank_id}/dreams/stats`
- `GET /v1/default/banks/{bank_id}/brain/influence`

## Async Retain Example

When retaining large batches of memories, use `async=true` to process in the background. The response includes an `operation_id` that you can use to poll for completion.

### 1. Submit async retain request

```bash
curl -X POST "http://localhost:8000/v1/default/banks/my-bank/memories" \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {"content": "Alice joined Google in 2023"},
      {"content": "Bob prefers Python over JavaScript"}
    ],
    "async": true
  }'
```

Response:
```json
{
  "success": true,
  "bank_id": "my-bank",
  "items_count": 2,
  "async": true,
  "operation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### 2. Poll for operation status

```bash
curl "http://localhost:8000/v1/default/banks/my-bank/operations"
```

Response:
```json
{
  "bank_id": "my-bank",
  "operations": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "task_type": "retain",
      "items_count": 2,
      "document_id": null,
      "created_at": "2024-01-15T10:30:00Z",
      "status": "completed",
      "error_message": null
    }
  ]
}
```

### Operation Status Values

| Status | Description |
|--------|-------------|
| `pending` | Operation is queued and waiting to be processed |
| `completed` | Operation finished successfully |
| `failed` | Operation failed (check `error_message` for details) |

## Next Steps

- [**Documents**](./documents) — Track document sources
- [**Memory Banks**](./memory-banks) — Configure bank settings
