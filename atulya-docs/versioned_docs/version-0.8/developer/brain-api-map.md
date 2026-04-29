---
title: Brain API — Semantic Map
description: Complete semantic map of all 113 endpoints and 186 schemas. Every field, every enum, every design pattern.
sidebar_label: Brain API Map
---

# Atulya Brain API — Complete Semantic Map

> Source of truth: `atulya-brain-openapi.json` (741KB, 113 endpoints, 186 schemas)
> API Version: 0.8.4 | License: Apache 2.0
> Local: `http://localhost:8888` | Auth: Bearer token
> Generated: 2026-04-28 | Multi-pass verified: 0 gaps

---

## 1. ARCHITECTURE CORE

**Bank** = isolated memory container. Every operation scoped to a bank_id.
Each bank has: memories, entities, graph, mental models, directives, dreams, disposition, config, documents, tags, codebases, webhooks.

**Multi-tenant**: schema-level isolation. Admin can list tenants, banks per tenant.

**Async model**: Heavy ops (retain, reflect, consolidation, dream, mental model refresh, brain learn, codebase import) return `operation_id`. Poll via `/operations/{id}` (status: pending|completed|failed|not_found) or `/operations/{id}/result`. Can cancel, retry failed ops. Batch ops have `ChildOperationStatus` (operation_id, status, sub_batch_index, items_count, error_message).

**Bank creation params** (`PUT /banks/{bank_id}`) — `CreateBankRequest`:
- `reflect_mission: string|null` — guides how Reflect interprets and uses memories
- `retain_mission: string|null` — steers what gets extracted during retain()
- `retain_extraction_mode: string|null` — concise (default) | verbose | custom
- `retain_custom_instructions: string|null` — custom extraction prompt (active when mode=custom)
- `retain_chunk_size: integer|null` — max token size per content chunk
- `bank_preset: string|null` — starter kit (e.g., 'codebase' tunes retain/reflect/observations for repos)
- `enable_observations: boolean|null` — toggle automatic observation consolidation on/off
- `observations_mission: string|null` — custom consolidation rules (replaces built-in rules entirely)
- `name: string|null` — display label
- `disposition: DispositionTraits|null`, `disposition_skepticism/literalism/empathy: integer|null`
- `mission: string|null`, `background: string|null` — (deprecated, use reflect_mission)

**Processing pipeline**: Raw content → Retain → Fact extraction → Consolidation → Observations → Mental Models / Graph / Entity Intelligence / Dreams

**Budget** (used by Recall & Reflect): `low` | `mid` | `high` — controls search depth and reasoning thoroughness.

**Feature flags** (`GET /version` → `VersionResponse`):
- `api_version: string`
- `features: FeaturesInfo` — `observations: boolean`, `timeline_v2: boolean`, `mcp: boolean`, `worker: boolean`, `bank_config_api: boolean`, `file_upload_api: boolean`, `brain_runtime: boolean`, `sub_routine: boolean`, `brain_import_export: boolean`

---

## 2. CORE MEMORY SYSTEM (The Foundation)

### Retain (Ingest)

```
POST /v1/default/banks/{bank_id}/memories
  Body: RetainRequest
  Response: RetainResponse
```

**RetainRequest**:
- `items: array<MemoryItem>` — array of memory items to ingest
- `async: boolean` (default: false) — if true, process in background
- `document_tags: array|null` — (deprecated, use item-level tags)

**MemoryItem**:
- `content: string` — raw text (required)
- `timestamp: string|null` — ISO 8601 datetime, null=now, "unset"=timeless
- `context: string|null` — freeform context string
- `metadata: object|null` — key-value pairs (string: string) (source, channel, etc.)
- `document_id: string|null` — groups items into documents (enables replace/append)
- `entities: array<EntityInput>|null` — pre-extracted entities to merge with auto-extracted. EntityInput: `text: string`, `type: string|null`
- `tags: array<string>|null` — visibility scoping for recall filtering
- `observation_scopes: string|array|null` — per_tag | combined | all_combinations | custom list of tag lists
- `update_mode: string|null` — replace (default) | append — for document_id dedup

**RetainResponse**: `success: boolean`, `bank_id: string`, `items_count: integer`, `async: boolean`, `operation_id: string|null`, `usage: TokenUsage|null`

**TokenUsage**: `input_tokens: integer`, `output_tokens: integer`, `total_tokens: integer`

```
POST /v1/default/banks/{bank_id}/files/retain
  Body: multipart (archive file + request JSON)
  Response: FileRetainResponse {operation_ids: array<string>}
```

Upload files (PDF, DOCX, etc.), auto-convert to markdown, retain as memories.

### Recall (Retrieve)

```
POST /v1/default/banks/{bank_id}/memories/recall
  Body: RecallRequest
  Response: RecallResponse
```

**RecallRequest**:
- `query: string` (required)
- `types: array<string>|null` — world | experience | observation (defaults to world+experience)
- `budget: Budget` (default: mid)
- `max_tokens: integer` (default: 4096)
- `trace: boolean` (default: false) — debug trace with timing
- `query_timestamp: string|null` — ISO datetime for temporal context
- `include: IncludeOptions` (default: entities enabled)
- `tags: array<string>|null` — filter by tags
- `tags_match: string` (default: any) — any | all | any_strict | all_strict
- `tag_groups: array<TagGroup>|null` — compound boolean predicates (mutually exclusive with tags)

**IncludeOptions**:
- `entities: EntityIncludeOptions|null` (default: `max_tokens: 500`) — entity observations
- `chunks: ChunkIncludeOptions|null` (default: null) — raw source chunks. ChunkIncludeOptions: `max_tokens: integer`
- `source_facts: SourceFactsIncludeOptions|null` (default: null) — SourceFactsIncludeOptions: `max_tokens: integer` (default 4096, -1=unlimited), `max_tokens_per_observation: integer` (default -1)

**Tag Groups** (compound boolean predicates):
- `TagGroupLeaf`: `{tags: array<string>, match: any|all|any_strict|all_strict}`
- `TagGroupAnd`: `{and: array<TagGroup>}`
- `TagGroupOr`: `{or: array<TagGroup>}`
- `TagGroupNot`: `{not: TagGroup}`

**RecallResponse**:
- `results: array<RecallResult>`
- `trace: object|null`
- `entities: object|null` — map of entity name → `EntityStateResponse` (canonical_name, entity_id, observations[])
- `chunks: object|null` — map of chunk_id → `ChunkData` (id, chunk_index, text)
- `source_facts: object|null` — map of fact_id → RecallResult

**RecallResult**: `id: string`, `text: string`, `type: string|null`, `entities: array<string>|null`, `context: string|null`, `occurred_start: string|null`, `occurred_end: string|null`, `mentioned_at: string|null`, `document_id: string|null`, `metadata: object|null`, `chunk_id: string|null`, `tags: array<string>|null`, `source_fact_ids: array<string>|null`

**Key mechanism**: Uses spreading activation over the memory graph — not just vector similarity.

### Reflect (Synthesize)

```
POST /v1/default/banks/{bank_id}/reflect
  Body: ReflectRequest
  Response: ReflectResponse

POST /v1/default/banks/{bank_id}/reflect/submit
  Body: ReflectRequest
  Response: AsyncOperationSubmitResponse {operation_id: string, status: string}
```

**ReflectRequest**:
- `query: string` (required)
- `budget: Budget` (default: low)
- `max_tokens: integer` (default: 4096)
- `include: ReflectIncludeOptions`
- `response_schema: object|null` — JSON Schema for structured output
- `tags: array<string>|null` / `tags_match` / `tag_groups`
- `context: string|null` — (deprecated, concatenate with query instead)

**ReflectIncludeOptions**:
- `facts: FactsIncludeOptions|null` (default: null) — set to {} to enable based_on evidence
- `tool_calls: ToolCallsIncludeOptions|null` (default: null) — `{output: boolean (default true)}` — set to {} for full trace, `{output: false}` for inputs only

**ReflectResponse**:
- `text: string` — markdown-formatted synthesis
- `based_on: ReflectBasedOn|null` — evidence used:
  - `memories: array<ReflectFact>` — `{id, text, type, context, occurred_start, occurred_end}`
  - `mental_models: array<ReflectMentalModel>` — `{id, text, context}`
  - `directives: array<ReflectDirective>` — `{id, name, content}`
- `structured_output: object|null` — parsed per response_schema
- `usage: TokenUsage|null`
- `trace: ReflectTrace|null`:
  - `tool_calls: array<ReflectToolCall>` — `{tool: string, input: object, output: object|null, duration_ms: integer, iteration: integer}`
  - `llm_calls: array<ReflectLLMCall>` — `{scope: string, duration_ms: integer}`

### Memory CRUD

```
GET    /v1/default/banks/{bank_id}/memories/list
  Query: type: string|null, q: string|null, limit: integer, offset: integer
  Response: ListMemoryUnitsResponse {items: array, total: integer, limit: integer, offset: integer}

GET    /v1/default/banks/{bank_id}/memories/{memory_id}
  # Get single memory unit with all metadata

GET    /v1/default/banks/{bank_id}/memories/{memory_id}/history
  # Get observation history with source facts resolved

DELETE /v1/default/banks/{bank_id}/memories/{memory_id}/observations
  Response: ClearMemoryObservationsResponse {deleted_count: integer}

DELETE /v1/default/banks/{bank_id}/memories
  Query: type: string|null
  Response: DeleteResponse {success: boolean, message: string|null, deleted_count: integer|null}
```

### Memory Types
- **world**: General knowledge about people, places, events, things
- **experience**: Conversations, events that happened
- **observation**: Consolidated knowledge (auto-generated from world/experience via consolidation)

### Chunks

```
GET /v1/default/chunks/{chunk_id}
  Response: ChunkResponse
```

Global chunk lookup by ID.

---

## 3. ENTITY SYSTEM

```
GET    /v1/default/banks/{bank_id}/entities
  Query: limit: integer, offset: integer
  Response: EntityListResponse {items: array, total: integer, limit: integer, offset: integer}

GET    /v1/default/banks/{bank_id}/entities/{entity_id}
  Response: EntityDetailResponse

POST   /v1/default/banks/{bank_id}/entities/{entity_id}/regenerate  # deprecated
  Response: EntityDetailResponse

GET    /v1/default/banks/{bank_id}/entities/{entity_id}/trajectory
  Response: EntityTrajectoryResponse

POST   /v1/default/banks/{bank_id}/entities/{entity_id}/trajectory/recompute
  Response: EntityTrajectoryRecomputeResponse

GET    /v1/default/banks/{bank_id}/entity-intelligence
  Response: EntityIntelligenceResponse

POST   /v1/default/banks/{bank_id}/entity-intelligence/recompute
  Response: EntityIntelligenceRecomputeResponse
```

**EntityDetailResponse**: `id: string`, `canonical_name: string`, `mention_count: integer`, `first_seen: string|null`, `last_seen: string|null`, `metadata: object|null`, `observations: array<EntityObservationResponse>` where EntityObservationResponse = `{text: string, mentioned_at: string|null}`

**EntityTrajectoryResponse** (HMM-based temporal modeling):
- `entity_id: string`, `bank_id: string`, `computed_at: string|null`
- `state_vocabulary: array<string>` — possible states for this entity
- `vocabulary_hash: string` — hash for cache invalidation
- `transition_matrix: array` — HMM transition probabilities
- `current_state: string` — current inferred state
- `viterbi_path: array<TrajectoryViterbiStepResponse>` — most likely state sequence. Each step: `{unit_id: string, state: string, occurred_sort_at: string, fact_preview: string}`
- `forecast_horizon: integer`, `forecast_distribution: object` — predicted future states
- `forward_log_prob: number|null` — log probability of observed sequence
- `anomaly_score: number|null` — how anomalous current trajectory is
- `llm_model: string`, `prompt_version: string`

**EntityIntelligenceResponse** (bank-wide cross-entity analysis):
- `bank_id: string`, `computed_at: string|null`, `entity_count: integer`, `source_entity_count: integer`
- `entity_snapshot_hash: string` — cache invalidation
- `content: string` — markdown narrative
- `structured_content: object` — machine-readable analysis
- `entity_context: object` — per-entity context used
- `delta_metadata: object` — what changed since last compute
- `llm_model: string`, `prompt_version: string`

---

## 4. GRAPH INTELLIGENCE

Memory graph = nodes (facts) + edges (relationships between facts/entities).

```
GET  /v1/default/banks/{bank_id}/graph
  Query: type: string|null, limit: integer, q: string|null, tags: array|null, tags_match: string
  Response: GraphDataResponse

GET  /v1/default/banks/{bank_id}/graph/summary
  Query: surface: string [state|evidence], type: string|null, q: string|null, tags: array|null, tags_match: string [any|all|any_strict|all_strict], confidence_min: number, node_kind: string [all|entity|topic], window_days: integer|null
  Response: GraphSummaryResponse

GET  /v1/default/banks/{bank_id}/graph/neighborhood
  Query: surface: string [state|evidence], type: string|null, q: string|null, tags, tags_match, confidence_min, node_kind, window_days, focus_ids: array|null, depth: integer, limit_nodes: integer, limit_edges: integer
  Response: GraphNeighborhoodResponse

GET  /v1/default/banks/{bank_id}/graph/intelligence
  Query: type: string|null, limit: integer, q: string|null, tags, tags_match [any|all|any_strict|all_strict], confidence_min: number, node_kind [all|entity|topic], window_days: integer|null
  Response: GraphIntelligenceResponse

POST /v1/default/banks/{bank_id}/graph/investigate
  Body: GraphInvestigationRequest
  Response: GraphInvestigationResponse
```

**Graph surfaces**: `state` (current knowledge topology) vs `evidence` (provenance chains). Mode hints: detail|compact|overview.

**GraphDataResponse**: `nodes: array<GraphNodeResponse>`, `edges: array<GraphEdgeResponse>`, `table_rows: array<GraphTableRowResponse>`, `total_units: integer`, `limit: integer`

**GraphSummaryResponse**: `surface: string [state|evidence]`, `mode_hint: string [detail|compact|overview]`, `total_nodes: integer`, `total_edges: integer`, `clusters: array<GraphSummaryItemResponse>`, `top_nodes: array<GraphSummaryItemResponse>`, `bundled_edges: array<GraphSummaryEdgeResponse>`, `initial_focus_ids: array`, `generated_at: string`, `cached: boolean`

**GraphSummaryItemResponse**: `id`, `kind` (cluster|node), `title`, `subtitle`, `preview_labels: array`, `member_count: integer`, `status_tone` (stable|changed|contradictory|stale|neutral), `display_priority: number`, `render_mode_hint` (detail|compact|overview), `cluster_membership: array`, `node_ref: string|null`

**GraphSummaryEdgeResponse**: `id`, `source_id`, `target_id`, `weight`

**GraphNeighborhoodResponse**: `surface: string [state|evidence]`, `mode_hint`, `focus_ids: array`, `nodes: array`, `edges: array`, `total_nodes: integer`, `total_edges: integer`, `has_more: boolean`, `cursor: string|null`, `generated_at: string`, `cached: boolean`

**GraphRelationEdgeResponse**: `id: string`, `source_id: string`, `target_id: string`, `relation_type: string`, `strength: number` (0-1), `evidence_count: integer`

**GraphInvestigationRequest**: `query: string`, `type: string|null`, `tags: array|null`, `tags_match [any|all|any_strict|all_strict]`, `confidence_min: number`, `node_kind [all|entity|topic]`, `window_days: integer|null`, `limit: integer`

**GraphInvestigationResponse**: `answer: string`, `focal_node_ids: array`, `focal_edge_ids: array`, `change_events: array<GraphChangeEventResponse>`, `evidence_path: array<GraphEvidencePathStepResponse>`, `recommended_checks: array`

**GraphChangeEventResponse**: `id: string`, `node_id: string`, `change_type: string [change|contradiction|stale]`, `before_state: string|null`, `after_state: string`, `confidence: number`, `time_window: string|null`, `evidence_ids: array`, `summary: string`

**GraphEvidencePathStepResponse**: `kind: string [node|event|memory]`, `id: string`, `label: string`, `timestamp: string|null`

---

## 5. MENTAL MODELS (Living Documents)

User-curated auto-updating documents that stay current as new memories arrive.

```
GET    /v1/default/banks/{bank_id}/mental-models
  Query: tags: array|null, tags_match [any|all|exact], limit: integer, offset: integer
  Response: MentalModelListResponse {items: array<MentalModelResponse>}

POST   /v1/default/banks/{bank_id}/mental-models
  Body: CreateMentalModelRequest
  Response: CreateMentalModelResponse

GET    /v1/default/banks/{bank_id}/mental-models/{mental_model_id}
  Response: MentalModelResponse

PATCH  /v1/default/banks/{bank_id}/mental-models/{mental_model_id}
  Body: UpdateMentalModelRequest
  Response: MentalModelResponse

DELETE /v1/default/banks/{bank_id}/mental-models/{mental_model_id}

GET    /v1/default/banks/{bank_id}/mental-models/{mental_model_id}/history

POST   /v1/default/banks/{bank_id}/mental-models/{mental_model_id}/refresh
  Response: AsyncOperationSubmitResponse
```

**CreateMentalModelRequest**: `id: string|null` (custom ID), `name: string`, `source_query: string`, `tags: array|null`, `max_tokens: integer` (256-8192), `trigger: MentalModelTrigger|null`

**UpdateMentalModelRequest**: `name: string|null`, `source_query: string|null`, `max_tokens: integer|null`, `tags: array|null`, `trigger: MentalModelTrigger|null`

**MentalModelResponse**: `id: string`, `bank_id: string`, `name: string`, `source_query: string`, `content: string` (auto-generated markdown), `tags: array` (default []), `max_tokens: integer` (default 2048), `trigger: MentalModelTrigger`, `last_refreshed_at: string|null`, `created_at: string|null`, `reflect_response: object|null` (full reflect payload including based_on)

**MentalModelTrigger**:
- `mode: string [full|delta]` — full regenerates entirely; delta does surgical edits, only changes what new facts contradict. Falls back to full if no existing content or source_query changed.
- `refresh_after_consolidation: boolean` (default false) — auto-refresh when new observations created (real-time mode)

---

## 6. DIRECTIVES (Hard Rules)

Injected into all prompts. Shape how the brain behaves.

```
GET    /v1/default/banks/{bank_id}/directives
  Query: tags: array|null, tags_match [any|all|exact], active_only: boolean, limit: integer, offset: integer
  Response: DirectiveListResponse {items: array<DirectiveResponse>}

POST   /v1/default/banks/{bank_id}/directives
  Body: CreateDirectiveRequest
  Response: DirectiveResponse

GET    /v1/default/banks/{bank_id}/directives/{directive_id}
  Response: DirectiveResponse

PATCH  /v1/default/banks/{bank_id}/directives/{directive_id}
  Body: UpdateDirectiveRequest
  Response: DirectiveResponse

DELETE /v1/default/banks/{bank_id}/directives/{directive_id}
```

**CreateDirectiveRequest**: `name: string`, `content: string`, `priority: integer` (higher = injected first), `is_active: boolean`, `tags: array|null`

**UpdateDirectiveRequest**: `name: string|null`, `content: string|null`, `priority: integer|null`, `is_active: boolean|null`, `tags: array|null`

**DirectiveResponse**: `id: string`, `bank_id: string`, `name: string`, `content: string`, `priority: integer`, `is_active: boolean`, `tags: array`, `created_at: string`, `updated_at: string`

---

## 7. DREAMS & TRANCE (Autonomous Processing)

The brain's "sleep cycle" — autonomous knowledge synthesis.

```
POST /v1/default/banks/{bank_id}/dreams/trigger
  Body: DreamSubmitRequest {trigger_source: string [manual|event|cron], run_type: string [dream|trance]}
  Response: ConsolidationResponse

GET  /v1/default/banks/{bank_id}/dreams
  Query: limit: integer
  Response: DreamRunListResponse {items: array<DreamRunResponse>}

GET  /v1/default/banks/{bank_id}/dreams/stats
  Response: DreamStatsResponse

POST /v1/default/banks/{bank_id}/dreams/predictions/{prediction_id}/outcome
  Body: DreamPredictionOutcomeRequest {status: string [confirmed|contradicted|request_more_evidence], note: string|null, evidence_ids: array}

POST /v1/default/banks/{bank_id}/dreams/proposals/{proposal_id}/review
  Body: DreamProposalReviewRequest {action: string [approve|reject|request_more_evidence], note: string|null}
```

**DreamRunResponse**:
- `run_id: string`, `bank_id: string`, `status: string`, `run_type: string`, `trigger_source: string`
- `created_at: string`, `updated_at: string|null`
- `narrative_html: string|null` — HTML-rendered dream narrative
- `summary: string|null`
- `evidence_basis: object` — what facts informed this dream
- `signals: object` — detected patterns/signals
- `predictions: array` — testable hypotheses
- `growth_hypotheses: array` — growth direction hypotheses
- `promotion_proposals: array` — memory promotion proposals
- `validation_outcomes: array` — tracked validation results
- `confidence: object` — confidence metrics
- `novelty_score: number` — how novel this dream run is
- `maturity_tier: string` — dream maturity level
- `quality_score: number` — overall quality
- `failure_reason: string|null`
- `legacy_run: boolean`, `source_artifact_id: string|null`

**DreamStatsResponse**:
- `bank_id: string`, `total_runs: integer`, `last_run_at: string|null`
- `avg_quality: number`, `avg_tokens: number`, `avg_output_tokens: number`
- `distillation_pass_rate: number`, `distilled_count: integer`
- `duplicate_suppression_count: integer`
- `prediction_confirmation_rate: number`
- `unresolved_prediction_backlog: integer`
- `avg_novelty: number`, `failed_run_count: integer`, `validation_rate: number`

Influence score has a `.dream` component — dreams affect memory ranking.

---

## 8. DISPOSITION (Personality)

```
GET /v1/default/banks/{bank_id}/profile
  Response: BankProfileResponse

PUT /v1/default/banks/{bank_id}/profile
  Body: UpdateDispositionRequest {disposition: DispositionTraits}
  Response: BankProfileResponse
```

**DispositionTraits** (influences memory formation and interpretation):
- `skepticism: integer` (1-5): trusting → skeptical
- `literalism: integer` (1-5): flexible → literal
- `empathy: integer` (1-5): detached → empathetic

**BankProfileResponse** includes disposition + mission.

**BankListItem**: `bank_id: string`, `name: string|null`, `disposition: DispositionTraits`, `mission: string|null`, `created_at: string|null`, `updated_at: string|null`

---

## 9. CONSOLIDATION (Memory Compression)

```
POST /v1/default/banks/{bank_id}/consolidate
  Response: ConsolidationResponse

POST /v1/admin/consolidate/{schema}
  # Trigger for all banks in a schema

DELETE /v1/default/banks/{bank_id}/observations
  Response: DeleteResponse
```

Transforms raw world/experience facts into observations (compressed knowledge).
- Delta-aware: only processes new/changed content
- Triggers mental model refresh if configured
- Fires `consolidation.completed` webhook

---

## 10. BRAIN RUNTIME & INFLUENCE

### Brain Cache

```
GET  /v1/default/banks/{bank_id}/brain/status
  Response: BrainRuntimeStatusResponse

GET  /v1/default/banks/{bank_id}/brain/export
  # Returns .brain binary snapshot

POST /v1/default/banks/{bank_id}/brain/import
  Response: BrainImportResponse {bank_id: string, file_path: string, size_bytes: integer, format_version: string|null}

POST /v1/default/banks/{bank_id}/brain/import/validate
  Response: BrainImportValidationResponse {valid: boolean, version: integer|null, reason: string|null}
```

**BrainRuntimeStatusResponse**:
- `enabled: boolean` — whether brain runtime is on
- `circuit_open: boolean` — circuit breaker (auto-disables on repeated failures)
- `failure_count: integer` — consecutive failure count
- `bank_id: string`, `file_path: string`
- `exists: boolean`, `size_bytes: integer`
- `last_modified_at: string|null`
- `source_snapshot_id: string|null`, `generated_at: string|null`
- `native_library_loaded: boolean` — whether compiled native binary cache is active
- `format_version: string|null` — snapshot format version
- `model_signature: string|null` — identifies which model generated the cache
- `compatibility_reason: string|null` — explains incompatibility if any
- `metrics: object` — runtime performance metrics

### Brain-to-Brain Learning

```
POST /v1/default/banks/{bank_id}/brain/learn
  Body: BrainLearnRequest
  Response: BrainLearnResponse
```

**BrainLearnRequest**:
- `remote_endpoint: string` — URL of remote Atulya API (e.g. http://host:8888)
- `remote_bank_id: string` — bank ID on remote instance
- `remote_api_key: string` — optional API key for remote
- `learning_type: string [auto|distilled|structured|raw_mirror]`
- `mode: string [incremental|full_copy]`
- `horizon_hours: integer`

### Influence Analytics

```
GET /v1/default/banks/{bank_id}/brain/influence
  Query: window_days: integer, top_k: integer, entity_type: string
  Response: BrainInfluenceResponse
```

**BrainInfluenceResponse**: `bank_id: string`, `window_days: integer`, `entity_type: string`, `leaderboard: array<InfluenceRow>`, `heatmap: array<InfluenceHeatmapPoint>`, `trend: array<InfluenceTrendPoint>`, `anomalies: array`, `summary: object`

**InfluenceRow**: `id: string`, `type: string`, `text: string`, `access_count: integer`, `influence_score: number`, `contribution: InfluenceContribution`, `last_accessed_at: string|null`

**InfluenceContribution**: `recency: number`, `freq: number`, `graph: number`, `rerank: number`, `dream: number` — each factor's weight in final score.

**InfluenceHeatmapPoint**: `weekday: integer`, `hour_utc: integer`, `count: integer`, `score: number`

**InfluenceTrendPoint**: `index: integer`, `raw: number`, `ewma: number`, `lower: number`, `upper: number`

---

## 11. SUB-ROUTINE (Activity Learning)

Brain learns when you're active and optimizes accordingly.

```
POST /v1/default/banks/{bank_id}/sub-routine
  Body: SubRoutineSubmitRequest {mode: string [warmup|incremental|full_copy], horizon_hours: integer (1-168, default 24), force_rebuild: boolean}
  Response: ConsolidationResponse

GET  /v1/default/banks/{bank_id}/sub-routine/histogram
  Response: SubRoutineHistogramResponse {bank_id: string, histogram: array<PredictionPoint>, sample_count: integer, source_snapshot_id: string|null, model_signature: string|null}

GET  /v1/default/banks/{bank_id}/sub-routine/predictions
  Query: horizon_hours: integer
  Response: SubRoutinePredictionResponse {bank_id: string, horizon_hours: integer, predictions: array<PredictionPoint>, sample_count: integer, source_snapshot_id: string|null, model_signature: string|null}
```

**PredictionPoint**: `hour_utc: integer`, `score: number`

---

## 12. ANOMALY DETECTION

```
POST /v1/default/banks/{bank_id}/anomaly/intelligence
  Body: AnomalyIntelligenceRequest {limit: integer, status: string|null, anomaly_types: array|null, min_severity: number|null}
  Response: AnomalyIntelligenceResponse
```

**AnomalyIntelligenceResponse** includes:
- `events: array<AnomalyEventResponse>`
- `summary: AnomalyIntelligenceSummaryResponse`

**AnomalyEventResponse**: `id: string`, `bank_id: string`, `anomaly_type: string`, `severity: number`, `status: string [open|acknowledged|resolved|suppressed]`, `unit_ids: array`, `entity_ids: array`, `description: string`, `metadata: object`, `detected_at: string|null`, `resolved_at: string|null`, `resolved_by: string|null`, `corrections: array<AnomalyCorrectionResponse>`

**AnomalyCorrectionResponse**: `id: string`, `bank_id: string`, `anomaly_id: string`, `correction_type: string`, `target_unit_id: string|null`, `before_state: object`, `after_state: object`, `confidence_delta: number|null`, `applied_at: string|null`, `applied_by: string`

**AnomalyIntelligenceSummaryResponse**: `total_events: integer`, `open_events: integer`, `resolved_events: integer`, `avg_severity: number`, `by_type: object`

---

## 13. CODEBASE INTELLIGENCE

Full code understanding pipeline — import, parse, review, curate, impact analyze.

### Import

```
POST /v1/default/banks/{bank_id}/codebases/import/github
  Body: CodebaseImportGithubRequest {owner: string|null, repo: string|null, ref: string|null, repo_url: string|null, root_path: string|null, include_globs: array, exclude_globs: array, refresh_existing: boolean}
  Response: CodebaseGithubImportResponse

POST /v1/default/banks/{bank_id}/codebases/import/zip
  Body: multipart (archive + request)
  Response: CodebaseImportResponse
```

### Codebase CRUD

```
GET  /v1/default/banks/{bank_id}/codebases
  Response: CodebaseListResponse {items: array}

GET  /v1/default/banks/{bank_id}/codebases/{codebase_id}
  Response: CodebaseResponse
```

**CodebaseResponse**: `id: string`, `bank_id: string`, `name: string`, `source_type: string`, `source_config: CodebaseSourceConfigResponse` (owner, repo, repo_url, ref, root_path, include_globs, exclude_globs), `current_snapshot_id: string|null`, `approved_snapshot_id: string|null`, `source_ref: string|null`, `source_commit_sha: string|null`, `snapshot_status: string|null`, `approved_source_ref: string|null`, `approved_source_commit_sha: string|null`, `approved_snapshot_status: string|null`, `approval_status: string|null`, `memory_status: string|null`, `stats: CodebaseSnapshotStatsResponse`, `review_counts: CodebaseReviewCountsResponse`, `cluster_count: integer`, `related_chunk_count: integer`, `parse_coverage: number`, `created_at/updated_at/snapshot_created_at/snapshot_updated_at/approved_snapshot_updated_at`

### Analysis Artifacts

```
GET /v1/default/banks/{bank_id}/codebases/{codebase_id}/artifacts/repo-map
  Query: snapshot_id: string|null
  Response: CodebaseRepoMapResponse {codebase_id: string, snapshot_id: string|null, generated_at: string|null, repo_map: object|null}

GET /v1/default/banks/{bank_id}/codebases/{codebase_id}/artifacts/modules
  Query: snapshot_id: string|null, limit: integer
  Response: CodebaseModuleBriefsResponse

GET /v1/default/banks/{bank_id}/codebases/{codebase_id}/artifacts/symbols
  Query: snapshot_id: string|null, limit: integer, cursor: string|null
  Response: CodebaseSymbolCardListResponse

GET /v1/default/banks/{bank_id}/codebases/{codebase_id}/artifacts/symbols/{symbol_id}
  Query: snapshot_id: string|null
  Response: CodebaseSymbolCardResponse {codebase_id: string, snapshot_id: string, symbol_card: object}
```

### Review Pipeline

```
GET  /v1/default/banks/{bank_id}/codebases/{codebase_id}/review
  Response: CodebaseReviewResponse

GET  /v1/default/banks/{bank_id}/codebases/{codebase_id}/chunks
  Query: path_prefix, language, cluster_id, route_target, changed_only, kind, q, limit, cursor, snapshot_id, min_significance, max_significance, file_role, auto_route_reason, has_safety_tag, route_source, order_by
  Response: CodebaseChunksResponse

GET  /v1/default/banks/{bank_id}/codebases/{codebase_id}/chunks/{chunk_id}
  Response: CodebaseChunkDetailResponse

POST /v1/default/banks/{bank_id}/codebases/{codebase_id}/review/route
  Body: CodebaseRouteRequest {item_ids: array, target: string [memory|research|dismissed|unrouted], queue_memory_import: boolean, memory_ingest_mode: string [direct|retain]}
  Response: CodebaseRouteResponse

GET  /v1/default/banks/{bank_id}/codebases/{codebase_id}/research
  Query: cursor: string|null, limit: integer
  Response: CodebaseChunksResponse
```

**CodebaseReviewCountsResponse**: `unrouted: integer`, `memory: integer`, `research: integer`, `dismissed: integer`

**CodebaseChunkItemResponse**: `id: string`, `chunk_key: string`, `path: string`, `language: string|null`, `kind: string`, `label: string`, `preview_text: string`, `start_line: integer`, `end_line: integer`, `container: string|null`, `parent_symbol: string|null`, `parent_fq_name: string|null`, `parse_confidence: number`, `cluster_id: string|null`, `cluster_label: string|null`, `route_target: string`, `route_source: string|null`, `change_kind: string`, `related_count: integer`, `document_id: string|null`, `significance_score: number`, `significance_components: object|null`, `file_role: string|null`, `auto_route_reason: string|null`, `complexity_score: number|null`, `safety_tags: array`, `pagerank_centrality: number|null`, `fanin_count: integer`

**CodebaseChunkDetailResponse** (extends ChunkItemResponse with):
- `snapshot_id: string`, `content_text: string` (full code text)
- `related_chunks: array<CodebaseRelatedChunkResponse>`
- `symbols: array` — symbols defined in this chunk
- `impact_edges: array` — dependency edges
- `cluster_members: array` — other chunks in same cluster

### Intelligence

```
POST /v1/default/banks/{bank_id}/codebases/{codebase_id}/curate
  Body: CodebaseCurateRequest {intent: string, scope_hint: string|null, snapshot_id: string|null, top_k_clusters: integer, top_k_symbols: integer, include_dismissed: boolean}
  Response: CodebaseCurateResponse {codebase_id: string, snapshot_id: string|null, intent: string, scope_hint: string|null, clusters: array, symbol_cards: array, unclustered: array, total_candidates: integer}

POST /v1/default/banks/{bank_id}/codebases/{codebase_id}/impact
  Body: CodebaseImpactRequest {path: string|null, symbol: string|null, query: string|null, max_depth: integer, limit: integer}
  Response: CodebaseImpactResponse {codebase_id: string, snapshot_id: string|null, seed: CodebaseImpactSeedResponse|null, impacted_files: array<CodebaseImpactFileResponse>, matched_symbols: array, edges: array<CodebaseImpactEdgeResponse>, explanation: string}

GET  /v1/default/banks/{bank_id}/codebases/{codebase_id}/symbols
  Query: q: string, kind: string|null, path_prefix: string|null, language: string|null, limit: integer
  Response: CodebaseSymbolsResponse

GET  /v1/default/banks/{bank_id}/codebases/{codebase_id}/files
  Query: path_prefix: string|null, language: string|null, changed_only: boolean, snapshot_id: string|null
  Response: CodebaseFilesResponse
```

**CodebaseImpactSeedResponse**: `type: string`, `value: string`

**CodebaseImpactFileResponse**: `path: string`, `language: string|null`, `size_bytes: integer`, `content_hash: string`, `document_id: string|null`, `status: string`, `change_kind: string`, `chunk_count: integer`, `depth: integer`

**CodebaseImpactEdgeResponse**: `edge_type: string`, `from_path: string`, `from_symbol: string|null`, `to_path: string|null`, `to_symbol: string|null`, `target_ref: string|null`, `label: string|null`

**CodebaseFileItemResponse**: `path: string`, `language: string|null`, `size_bytes: integer`, `content_hash: string`, `document_id: string|null`, `status: string`, `change_kind: string`, `reason: string|null`, `chunk_count: integer`

### Approval & Refresh

```
POST /v1/default/banks/{bank_id}/codebases/{codebase_id}/approve
  Body: CodebaseApproveRequest {snapshot_id: string|null, memory_ingest_mode: string [direct|retain]}
  Response: CodebaseApproveResponse

POST /v1/default/banks/{bank_id}/codebases/{codebase_id}/refresh
  Body: CodebaseRefreshRequest {ref: string|null, full_rebuild: boolean}
  Response: CodebaseRefreshResponse
```

### Triage Settings

```
GET /v1/default/banks/{bank_id}/codebases/{codebase_id}/triage-settings
  Response: CodebaseTriageSettingsResponse

PUT /v1/default/banks/{bank_id}/codebases/{codebase_id}/triage-settings
  Body: CodebaseTriageSettings
  Response: CodebaseTriageSettingsResponse
```

**CodebaseTriageSettings**: `score_threshold_high: number`, `centrality_threshold: number`, `safety_threshold: number`, `embedding_provider: string`, `enable_safety_scan: boolean`, `enable_semgrep: boolean`, `semgrep_rulepack: string|null`, `scip_index_path: string|null` (SCIP semantic code index)

### Snapshot Stats

**CodebaseSnapshotStatsResponse**: `total_files: integer`, `indexed_files: integer`, `retained_files: integer`, `manifest_only_files: integer`, `excluded_files: integer`, `symbol_count: integer`, `edge_count: integer`, `added_files: integer`, `changed_files: integer`, `unchanged_files: integer`, `deleted_files: integer`, `chunk_count: integer`, `cluster_count: integer`, `related_chunk_count: integer`, `parse_coverage: number`, `review_counts: object|null`, `error: string|null`

---

## 14. TIMELINE

```
GET /v1/default/banks/{bank_id}/timeline
  Query: type: string|null, limit: integer, q: string|null, tags: array|null, tags_match [any|all|any_strict|all_strict]
  Response: TimelineResponse {items: array<TimelineItemResponse>, edges: array<TimelineEdgeResponse>, total_items: integer, limit: integer}
```

**TimelineItemResponse**:
- `id: string`, `kind: string [fact|observation|mental_model]`, `fact_type: string`, `text: string`
- `context: string|null`, `title: string|null`
- `anchor_at: string|null`, `anchor_kind: string` — how item is anchored in time
- `recorded_at: string|null`, `occurred_start: string|null`, `occurred_end: string|null`
- `temporal_direction: string` — forward/backward temporal flow
- `temporal_confidence: number|null` — confidence in temporal placement
- `temporal_reference_text: string|null` — original text that established the anchor
- `temporal: TimelineTemporalResponse` — nested temporal metadata
- `entities: array<string>`, `tags: array<string>`
- `source_memory_ids: array<string>` — provenance chain
- `proof_count: integer` (default 0) — how many source facts support this item

**TimelineTemporalResponse**: `anchor_at: string|null`, `anchor_kind: string`, `recorded_at: string|null`, `direction: string`, `confidence: number|null`, `reference_text: string|null`

**TimelineEdgeResponse**: `source: string`, `target: string`, `edge_kind: string [chronological|temporal|semantic|entity|causal|source|derived]`, `weight: number` (default 1.0)

---

## 15. DOCUMENTS & TAGS

### Documents

```
GET    /v1/default/banks/{bank_id}/documents
  Query: q: string|null, tags: array|null, tags_match: string, limit: integer, offset: integer
  Response: ListDocumentsResponse {items: array, total: integer, limit: integer, offset: integer}

GET    /v1/default/banks/{bank_id}/documents/{document_id}
  Response: DocumentResponse

DELETE /v1/default/banks/{bank_id}/documents/{document_id}
  Response: DeleteDocumentResponse
```

Source content containers from which memory units are extracted. Delete cascades to all associated memory units.

### Tags

```
GET /v1/default/banks/{bank_id}/tags
  Query: q: string|null (wildcard: user:*, *-fred), limit: integer, offset: integer
  Response: ListTagsResponse {items: array<TagItem>, total: integer, limit: integer, offset: integer}
```

**TagItem**: `tag: string`, `count: integer`

Tags are the primary mechanism for multi-context memory isolation within a single bank.

---

## 16. BANK CONFIG

```
GET    /v1/default/banks/{bank_id}/config
  Response: BankConfigResponse {bank_id: string, config: object, overrides: object}

PATCH  /v1/default/banks/{bank_id}/config
  Body: BankConfigUpdate
  Response: BankConfigResponse

DELETE /v1/default/banks/{bank_id}/config
  Response: BankConfigResponse
```

Hierarchical configuration: global → tenant → bank. `config` = fully resolved. `overrides` = bank-specific only. Keys accept Python field format (llm_provider) or environment variable format. Delete resets to defaults.

---

## 17. BANK CRUD

```
GET    /v1/default/banks
  Response: BankListResponse

PUT    /v1/default/banks/{bank_id}
  Body: CreateBankRequest
  Response: BankProfileResponse

PATCH  /v1/default/banks/{bank_id}
  Body: CreateBankRequest
  Response: BankProfileResponse

DELETE /v1/default/banks/{bank_id}
  Response: DeleteResponse

GET    /v1/default/banks/{bank_id}/stats
  Response: BankStatsResponse

POST   /v1/default/banks/{bank_id}/background  # deprecated, use mission
  Body: AddBackgroundRequest {content: string, update_disposition: boolean (deprecated)}
  Response: BackgroundResponse
```

---

## 18. OPERATIONS & WEBHOOKS

### Async Operations

```
GET    /v1/default/banks/{bank_id}/operations
  Query: status: string|null, type: string|null, limit: integer, offset: integer
  Response: OperationsListResponse {bank_id: string, total: integer, limit: integer, offset: integer, operations: array<OperationResponse>}

GET    /v1/default/banks/{bank_id}/operations/{operation_id}
  Response: OperationStatusResponse

DELETE /v1/default/banks/{bank_id}/operations/{operation_id}
  Response: CancelOperationResponse {success: boolean, message: string, operation_id: string}

GET    /v1/default/banks/{bank_id}/operations/{operation_id}/result
  Response: OperationResultResponse

POST   /v1/default/banks/{bank_id}/operations/{operation_id}/retry
  Response: RetryOperationResponse
```

**OperationResponse**: `id: string`, `task_type: string`, `items_count: integer`, `document_id: string|null`, `created_at: string`, `status: string`, `error_message: string|null`

**OperationStatusResponse**: `operation_id: string`, `status: string [pending|completed|failed|not_found]`, `operation_type: string|null`, `created_at/updated_at/completed_at: string|null`, `error_message: string|null`, `stage: string|null`, `result_metadata: object|null`, `child_operations: array<ChildOperationStatus>|null`

**ChildOperationStatus**: `operation_id: string`, `status: string`, `sub_batch_index: integer|null`, `items_count: integer|null`, `error_message: string|null`

**OperationResultResponse**: `operation_id: string`, `status [pending|completed|failed|not_found]`, `operation_type: string|null`, `created_at/updated_at/completed_at: string|null`, `error_message: string|null`, `stage: string|null`, `result: ReflectResponse|object|null`

**RetryOperationResponse**: `success: boolean`, `message: string`, `operation_id: string`, `retried_from_operation_id: string`, `bank_id: string`, `operation_type: string|null`

### Webhooks

```
POST   /v1/default/banks/{bank_id}/webhooks
  Body: CreateWebhookRequest
  Response: WebhookResponse

GET    /v1/default/banks/{bank_id}/webhooks
  Response: WebhookListResponse {items: array<WebhookResponse>}

PATCH  /v1/default/banks/{bank_id}/webhooks/{webhook_id}
  Body: UpdateWebhookRequest
  Response: WebhookResponse

DELETE /v1/default/banks/{bank_id}/webhooks/{webhook_id}
  Response: DeleteResponse

GET    /v1/default/banks/{bank_id}/webhooks/{webhook_id}/deliveries
  Query: limit: integer, cursor: string|null
  Response: WebhookDeliveryListResponse {items: array<WebhookDeliveryResponse>, next_cursor: string|null}
```

**CreateWebhookRequest**: `url: string`, `secret: string|null` (HMAC-SHA256), `event_types: array<string>` (supported: 'consolidation.completed'), `enabled: boolean`, `http_config: WebhookHttpConfig|null`

**UpdateWebhookRequest**: `url: string|null`, `secret: string|null` (omit to keep, null to clear), `event_types: array|null`, `enabled: boolean|null`, `http_config: WebhookHttpConfig|null`

**WebhookHttpConfig**: `method: string` (GET|POST, default POST), `timeout_seconds: integer` (default 30), `headers: object<string,string>`, `params: object<string,string>`

**WebhookResponse**: `id: string`, `bank_id: string|null`, `url: string`, `secret: string|null` (redacted), `event_types: array`, `enabled: boolean`, `http_config: WebhookHttpConfig`, `created_at/updated_at: string|null`

**WebhookDeliveryResponse**: `id: string`, `webhook_id: string|null`, `url: string`, `event_type: string`, `status: string`, `attempts: integer`, `next_retry_at: string|null`, `last_error: string|null`, `last_response_status: integer|null`, `last_response_body: string|null`, `last_attempt_at: string|null`, `created_at/updated_at: string|null`

---

## 19. ADMIN & SYSTEM

### API Keys

```
GET    /v1/admin/api-keys
  Query: schema: string

POST   /v1/admin/api-keys
  Query: schema: string
  Body: ApiKeyCreateRequest {name: string, role: string [superuser|admin|user], schema_name: string, allowed_bank_ids: array|null, expires_days: integer|null}
  Response: ApiKeyResponse

PATCH  /v1/admin/api-keys/{key_id}
  Query: schema: string
  Body: ApiKeyUpdateRequest
  Response: ApiKeyResponse

DELETE /v1/admin/api-keys/{key_id}
  Query: schema: string
```

**ApiKeyResponse**: `id: string`, `name: string`, `role: string`, `schema_name: string`, `allowed_bank_ids: array|null`, `created_at: string`, `expires_at: string|null`, `revoked_at: string|null`, `raw_key: string|null` (only returned on create, never again)

### Tenants & Workers

```
GET  /v1/admin/tenants
  # Response includes array<TenantSummaryResponse>

GET  /v1/admin/tenants/{schema}/banks

GET  /v1/admin/workers
  Query: schema: string
  # Response includes array<WorkerStatusResponse>

POST /v1/admin/workers/{worker_id}/decommission
  Query: schema: string
  Body: DecommissionRequest {release_stuck: boolean (default true)}
  Response: DecommissionResponse {worker_id: string, released_count: integer}

GET  /v1/admin/operations
  Query: schema: string, status: string|null, limit: integer
  # Cross-tenant operation listing
```

**TenantSummaryResponse**: `schema_name: string`, `bank_count: integer`

**WorkerStatusResponse**: `worker_id: string`, `schema_name: string`, `pending_count: integer`, `stuck_count: integer`, `last_seen_at: string|null`

Use `worker_id='__all_stuck__'` to release all tasks with no active worker.

### System Health

```
GET /health
  # Basic health check

GET /v1/admin/system/health
  Response: SystemHealthResponse {status: string, api_version: string, db_pool_min: integer, db_pool_max: integer, db_pool_size: integer, db_pool_free: integer, migration_version: string|null, worker_count: integer, admin_schema: string}

GET /metrics
  # Prometheus format

GET /version
  Response: VersionResponse {api_version: string, features: FeaturesInfo}
```

**FeaturesInfo**: `observations: boolean`, `timeline_v2: boolean`, `mcp: boolean`, `worker: boolean`, `bank_config_api: boolean`, `file_upload_api: boolean`, `brain_runtime: boolean`, `sub_routine: boolean`, `brain_import_export: boolean`

---

## 20. INTERCONNECTION MAP

```
Raw Content ─┬─► Retain ──► Facts (world/experience)
             │                    │
Files ───────┘                    ▼
                          Consolidation ──► Observations
                                │                │
                                ▼                ▼
                          Mental Models    Entity Intelligence
                          (auto-refresh)   (trajectories, HMM)
                                │                │
                                ▼                ▼
                    ┌─── Graph Intelligence ────┐
                    │   (state graph, changes,  │
                    │    contradictions, stale)  │
                    └───────────┬───────────────┘
                                │
                    ┌───────────▼───────────────┐
                    │        Reflect            │
                    │  (retrieves all layers,   │
                    │   applies directives,     │
                    │   returns synthesis)      │
                    └───────────┬───────────────┘
                                │
                    Dreams/Trance ◄── Sub-routine
                    (predictions,     (activity
                     proposals,        learning)
                     insights)
                                │
                    Anomaly Detection
                    (contradictions,
                     severity, corrections)
                                │
                    Brain Export/Import/Learn
                    (portable snapshots,
                     brain-to-brain transfer)

Codebases ──► Symbol Cards + Chunks ──► Review ──► Approve ──► Memory Hydration
                                                        │
                                                  Impact Analysis
                                                  Curate by Intent
```

---

## 21. KEY DESIGN PATTERNS

1. **Tag-based isolation**: Single bank, multiple contexts via tags. Compound boolean predicates (AND/OR/NOT via TagGroupLeaf/And/Or/Not).
2. **Document-centric updates**: document_id enables replace/append without duplication.
3. **Observation scoping**: per_tag | combined | all_combinations — controls consolidation granularity.
4. **Budget-based depth**: low/mid/high across recall and reflect — trade speed for thoroughness.
5. **Delta processing**: Consolidation and mental model refresh only process changes.
6. **Influence scoring**: Multi-factor (recency, frequency, graph centrality, rerank, dream contribution).
7. **Dual missions**: Banks have separate `reflect_mission` (interpretation) and `retain_mission` (extraction) — different prompts for reading vs writing memory.
8. **Extraction modes**: concise | verbose | custom — with fully custom extraction prompts.
9. **Circuit breaker**: Brain runtime auto-disables on failures, tracks failure_count, uses native compiled cache.
10. **Brain portability**: Export/import versioned snapshots. Learn from remote brains (auto/distilled/structured/raw_mirror).
11. **Disposition-driven**: Skepticism/literalism/empathy (1-5 scale) shape how memories are formed and interpreted.
12. **Dream cycle with validation loop**: Autonomous synthesis generates testable predictions (confirmed|contradicted|request_more_evidence), growth hypotheses, promotion proposals. Tracks novelty_score, maturity_tier, distillation_pass_rate, duplicate_suppression_count.
13. **Codebase-as-memory**: Code imported, chunked, scored (significance_score, pagerank_centrality, complexity_score, fanin_count), safety-scanned (safety_tags, semgrep, scip_index), reviewed, then hydrated into memory system.
14. **Graph dual surfaces**: state (current knowledge) vs evidence (provenance). Change events typed as change|contradiction|stale.
15. **Entity trajectory modeling**: HMM with state_vocabulary, transition_matrix, viterbi_path, forecast_distribution, anomaly_score.
16. **Hierarchical config**: global → tenant → bank override chain with full reset capability.

---

## 22. UNIQUE CAPABILITIES (What Makes This Different)

- **Graph Dual Surfaces**: `state` and `evidence` surfaces — state shows current knowledge topology, evidence shows provenance chains
- **Graph Investigation**: Natural language questions against knowledge graph → evidence paths + recommended checks
- **Entity Trajectories**: HMM-based temporal modeling with viterbi_path, forecast_distribution, anomaly_score
- **Dream/Trance System**: Autonomous "sleep cycle" generating narrative_html, predictions, growth_hypotheses, promotion_proposals
- **Brain-to-Brain Learning**: Federated knowledge — one Atulya learns from another (auto/distilled/structured/raw_mirror)
- **Anomaly Detection with Corrections**: Finds contradictions, provides before_state/after_state diffs with confidence_delta
- **Disposition Personality**: Memory formation influenced by skepticism/literalism/empathy traits (1-5 scale)
- **Sub-routine Activity Learning**: Brain learns temporal patterns, predicts active hours, has activity heatmap
- **Codebase Intelligence**: Full pipeline: import → parse → chunk → score (PageRank, significance, complexity, fan-in) → safety scan → review → curate by intent → impact analysis → memory hydration
- **Compound Tag Predicates**: Boolean logic (AND/OR/NOT nesting) for memory scoping
- **Mental Model Delta Mode**: Surgical updates to living documents — only changes what new facts contradict
- **Spreading Activation Recall**: Graph-based retrieval, not just vector similarity
- **Dual Mission Architecture**: Separate prompts for memory reading (reflect_mission) vs writing (retain_mission)
- **Configurable Extraction**: concise/verbose/custom modes with user-defined extraction prompts
- **Native Brain Cache**: Compiled binary cache with circuit breaker, format versioning, model signatures

---

*This file is a complete semantic compression of the full OpenAPI spec. Every endpoint, every schema, every field type, every enum value is captured. For raw JSON schemas, reference `atulya-brain-openapi.json`.*
