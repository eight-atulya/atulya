/**
 * Client for calling Control Plane API routes (which proxy to the dataplane via SDK)
 * This should be used in client components, not the SDK directly
 */

import { toast } from "sonner";

export interface WebhookHttpConfig {
  method: string;
  timeout_seconds: number;
  headers: Record<string, string>;
  params: Record<string, string>;
}

export interface Webhook {
  id: string;
  bank_id: string | null;
  url: string;
  event_types: string[];
  enabled: boolean;
  http_config: WebhookHttpConfig;
  created_at: string | null;
  updated_at: string | null;
}

export interface WebhookDelivery {
  id: string;
  webhook_id: string | null;
  url: string;
  event_type: string;
  status: string;
  attempts: number;
  next_retry_at: string | null;
  last_error: string | null;
  last_response_status: number | null;
  last_response_body: string | null;
  last_attempt_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MentalModel {
  id: string;
  bank_id: string;
  name: string;
  source_query: string;
  content: string;
  tags: string[];
  max_tokens: number;
  trigger: { refresh_after_consolidation: boolean };
  last_refreshed_at: string;
  created_at: string;
  reflect_response?: any;
}

export interface DreamPrediction {
  prediction_id: string | null;
  title: string;
  description: string;
  target_ref: string | null;
  target_kind: "entity" | "topic" | "bank" | "theme" | "memory";
  horizon: "near_term" | "mid_term" | "long_term";
  confidence: number;
  success_criteria: string[];
  expiration_window_days: number;
  status: "pending" | "confirmed" | "contradicted" | "unresolved";
  supporting_evidence_ids: string[];
  validation_notes: string | null;
}

export interface DreamGrowthHypothesis {
  title: string;
  description: string;
  confidence: number;
  signals: string[];
  blind_spot: string | null;
  opportunity: string | null;
}

export interface DreamPromotionProposal {
  proposal_id: string | null;
  proposal_type: "observation" | "mental_model" | "prediction_candidate" | "growth_candidate";
  title: string;
  content: string;
  confidence: number;
  tags: string[];
  supporting_evidence_ids: string[];
  review_status: "proposed" | "approved" | "rejected" | "needs_more_evidence";
  rationale: string | null;
}

export interface DreamValidationOutcome {
  outcome_id: string | null;
  prediction_id: string;
  status: "confirmed" | "contradicted" | "request_more_evidence";
  note: string | null;
  evidence_ids: string[];
  created_at: string | null;
}

export interface DreamArtifact {
  run_id: string;
  bank_id: string;
  status: "success" | "low_signal" | "duplicate_low_novelty" | "failed_llm" | "failed_validation";
  run_type: string;
  trigger_source: string;
  created_at: string;
  updated_at: string | null;
  narrative_html: string | null;
  summary: string | null;
  evidence_basis: Record<string, any>;
  signals: Record<string, any>;
  predictions: DreamPrediction[];
  growth_hypotheses: DreamGrowthHypothesis[];
  promotion_proposals: DreamPromotionProposal[];
  validation_outcomes: DreamValidationOutcome[];
  confidence: Record<string, any>;
  novelty_score: number;
  maturity_tier: "sparse" | "emerging" | "mature";
  failure_reason: string | null;
  quality_score: number;
  legacy_run: boolean;
  source_artifact_id: string | null;
}

export interface DreamStats {
  bank_id: string;
  total_runs: number;
  last_run_at: string | null;
  avg_quality: number;
  avg_tokens: number;
  avg_output_tokens: number;
  distillation_pass_rate: number;
  distilled_count: number;
  validation_rate: number;
  avg_novelty: number;
  failed_run_count: number;
  duplicate_suppression_count: number;
  prediction_confirmation_rate: number;
  unresolved_prediction_backlog: number;
}

function asNumber(value: unknown, fallback = 0): number {
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function asRecord(value: unknown): Record<string, any> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, any>)
    : {};
}

function normalizeDreamPrediction(raw: Partial<DreamPrediction>): DreamPrediction {
  return {
    prediction_id: raw.prediction_id ?? null,
    title: String(raw.title ?? ""),
    description: String(raw.description ?? ""),
    target_ref: raw.target_ref ?? null,
    target_kind: (raw.target_kind ?? "theme") as DreamPrediction["target_kind"],
    horizon: (raw.horizon ?? "near_term") as DreamPrediction["horizon"],
    confidence: asNumber(raw.confidence, 0),
    success_criteria: asArray<string>(raw.success_criteria),
    expiration_window_days: asNumber(raw.expiration_window_days, 14),
    status: (raw.status ?? "pending") as DreamPrediction["status"],
    supporting_evidence_ids: asArray<string>(raw.supporting_evidence_ids),
    validation_notes: raw.validation_notes ?? null,
  };
}

function normalizeDreamGrowthHypothesis(
  raw: Partial<DreamGrowthHypothesis>
): DreamGrowthHypothesis {
  return {
    title: String(raw.title ?? ""),
    description: String(raw.description ?? ""),
    confidence: asNumber(raw.confidence, 0),
    signals: asArray<string>(raw.signals),
    blind_spot: raw.blind_spot ?? null,
    opportunity: raw.opportunity ?? null,
  };
}

function normalizeDreamPromotionProposal(
  raw: Partial<DreamPromotionProposal>
): DreamPromotionProposal {
  return {
    proposal_id: raw.proposal_id ?? null,
    proposal_type: (raw.proposal_type ?? "observation") as DreamPromotionProposal["proposal_type"],
    title: String(raw.title ?? ""),
    content: String(raw.content ?? ""),
    confidence: asNumber(raw.confidence, 0),
    tags: asArray<string>(raw.tags),
    supporting_evidence_ids: asArray<string>(raw.supporting_evidence_ids),
    review_status: (raw.review_status ?? "proposed") as DreamPromotionProposal["review_status"],
    rationale: raw.rationale ?? null,
  };
}

function normalizeDreamValidationOutcome(
  raw: Partial<DreamValidationOutcome>
): DreamValidationOutcome {
  return {
    outcome_id: raw.outcome_id ?? null,
    prediction_id: String(raw.prediction_id ?? ""),
    status: (raw.status ?? "request_more_evidence") as DreamValidationOutcome["status"],
    note: raw.note ?? null,
    evidence_ids: asArray<string>(raw.evidence_ids),
    created_at: raw.created_at ?? null,
  };
}

function normalizeDreamArtifact(raw: Partial<DreamArtifact>): DreamArtifact {
  return {
    run_id: String(raw.run_id ?? ""),
    bank_id: String(raw.bank_id ?? ""),
    status: (raw.status ?? "failed_validation") as DreamArtifact["status"],
    run_type: String(raw.run_type ?? "dream"),
    trigger_source: String(raw.trigger_source ?? "manual"),
    created_at: String(raw.created_at ?? ""),
    updated_at: raw.updated_at ?? null,
    narrative_html: raw.narrative_html ?? null,
    summary: raw.summary ?? null,
    evidence_basis: asRecord(raw.evidence_basis),
    signals: asRecord(raw.signals),
    predictions: asArray<Partial<DreamPrediction>>(raw.predictions).map((item) =>
      normalizeDreamPrediction(item)
    ),
    growth_hypotheses: asArray<Partial<DreamGrowthHypothesis>>(raw.growth_hypotheses).map((item) =>
      normalizeDreamGrowthHypothesis(item)
    ),
    promotion_proposals: asArray<Partial<DreamPromotionProposal>>(raw.promotion_proposals).map(
      (item) => normalizeDreamPromotionProposal(item)
    ),
    validation_outcomes: asArray<Partial<DreamValidationOutcome>>(raw.validation_outcomes).map(
      (item) => normalizeDreamValidationOutcome(item)
    ),
    confidence: asRecord(raw.confidence),
    novelty_score: asNumber(raw.novelty_score, 0),
    maturity_tier: (raw.maturity_tier ?? "sparse") as DreamArtifact["maturity_tier"],
    failure_reason: raw.failure_reason ?? null,
    quality_score: asNumber(raw.quality_score, 0),
    legacy_run: Boolean(raw.legacy_run),
    source_artifact_id: raw.source_artifact_id ?? null,
  };
}

export interface BenchmarkLeaderboardSummary {
  scenario_count: number;
  recall_accuracy: number;
  contradiction_resolution_accuracy: number | null;
  skill_creation_precision: number;
  skill_reuse_success_rate: number | null;
  time_to_useful_answer_ms: number | null;
  token_cost_per_successful_action: number | null;
}

export interface BenchmarkResponse {
  available: boolean;
  mode: "deterministic" | "live-api";
  leaderboard: {
    benchmark_name: string;
    mode: string;
    scenario_count: number;
    strategies: Record<
      string,
      {
        overall: BenchmarkLeaderboardSummary;
        buckets: Record<string, BenchmarkLeaderboardSummary>;
      }
    >;
  } | null;
  markdown: string;
  generated_at: string | null;
  stdout?: string;
  stderr?: string;
}

export interface GraphStateNode {
  id: string;
  title: string;
  kind: "entity" | "topic";
  subtitle: string | null;
  current_state: string;
  status: "stable" | "changed" | "contradictory" | "stale";
  status_reason: string;
  confidence: number;
  change_score: number;
  last_changed_at: string | null;
  primary_timestamp: string | null;
  evidence_count: number;
  tags: string[];
  evidence_ids: string[];
}

export interface GraphRelationEdge {
  id: string;
  source_id: string;
  target_id: string;
  relation_type: string;
  strength: number;
  evidence_count: number;
}

export interface GraphChangeEvent {
  id: string;
  node_id: string;
  change_type: "change" | "contradiction" | "stale";
  before_state: string | null;
  after_state: string;
  confidence: number;
  time_window: string | null;
  evidence_ids: string[];
  summary: string;
}

export interface GraphEvidencePathStep {
  kind: "node" | "event" | "memory";
  id: string;
  label: string;
  timestamp: string | null;
}

export interface GraphIntelligenceResponse {
  nodes: GraphStateNode[];
  edges: GraphRelationEdge[];
  change_events: GraphChangeEvent[];
  total_nodes: number;
  generated_at: string;
  cached: boolean;
}

export interface GraphInvestigationResponse {
  answer: string;
  focal_node_ids: string[];
  focal_edge_ids: string[];
  change_events: GraphChangeEvent[];
  evidence_path: GraphEvidencePathStep[];
  recommended_checks: string[];
}

export type GraphRenderMode = "overview" | "compact" | "detail";

export interface GraphSummaryItem {
  id: string;
  kind: "cluster" | "node";
  title: string;
  subtitle: string | null;
  preview_labels: string[];
  member_count: number;
  status_tone: "stable" | "changed" | "contradictory" | "stale" | "neutral";
  display_priority: number;
  render_mode_hint: GraphRenderMode;
  cluster_membership: string[];
  node_ref: string | null;
}

export interface GraphSummaryEdge {
  id: string;
  source_id: string;
  target_id: string;
  weight: number;
  label: string | null;
}

export interface GraphSummaryResponse {
  surface: "state" | "evidence";
  mode_hint: GraphRenderMode;
  total_nodes: number;
  total_edges: number;
  clusters: GraphSummaryItem[];
  top_nodes: GraphSummaryItem[];
  bundled_edges: GraphSummaryEdge[];
  initial_focus_ids: string[];
  generated_at: string;
  cached: boolean;
}

export interface GraphNeighborhoodNode {
  id: string;
  node_type: "state" | "event" | "evidence";
  title: string;
  subtitle: string | null;
  preview: string | null;
  status_label: string | null;
  status_tone: "stable" | "changed" | "contradictory" | "stale" | "neutral";
  confidence: number | null;
  evidence_count: number | null;
  kind_label: string | null;
  meta: string | null;
  timestamp_label: string | null;
  reason: string | null;
  accent_color: string | null;
  display_priority: number;
  node_density_hint: number;
  cluster_membership: string | null;
  render_mode_hint: GraphRenderMode;
}

export interface GraphNeighborhoodEdge {
  id: string;
  source: string;
  target: string;
  kind: "relation" | "event" | "evidence";
  label: string | null;
  stroke: string | null;
  dashed: boolean;
  width: number;
  animated: boolean;
  priority: number;
}

export interface GraphNeighborhoodResponse {
  surface: "state" | "evidence";
  mode_hint: GraphRenderMode;
  focus_ids: string[];
  nodes: GraphNeighborhoodNode[];
  edges: GraphNeighborhoodEdge[];
  total_nodes: number;
  total_edges: number;
  has_more: boolean;
  cursor: string | null;
  generated_at: string;
  cached: boolean;
}

export interface ReflectResponse {
  text: string;
  based_on: {
    memories: Array<{
      id: string | null;
      text: string;
      type: string | null;
      context: string | null;
      occurred_start: string | null;
      occurred_end: string | null;
    }>;
    mental_models: Array<{
      id: string;
      text: string;
      context: string | null;
    }>;
    directives: Array<{
      id: string;
      name: string;
      content: string;
    }>;
  } | null;
  structured_output: Record<string, any> | null;
  usage: {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  } | null;
  trace: {
    tool_calls: Array<{
      tool: string;
      input: Record<string, any>;
      output: Record<string, any> | null;
      duration_ms: number;
      iteration: number;
    }>;
    llm_calls: Array<{
      scope: string;
      duration_ms: number;
    }>;
  } | null;
}

export interface OperationStatus {
  operation_id: string;
  status: "pending" | "completed" | "failed" | "not_found";
  operation_type: string | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  stage: string | null;
  result_metadata?: Record<string, any> | null;
}

export interface OperationResult extends OperationStatus {
  result: ReflectResponse | null;
}

export class ControlPlaneClient {
  private async fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
    try {
      const response = await fetch(path, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...options?.headers,
        },
      });

      if (!response.ok) {
        // Try to parse error response
        let errorMessage = `HTTP ${response.status}`;
        let errorDetails: string | undefined;

        try {
          const errorData = await response.json();
          errorMessage = errorData.error || errorMessage;
          errorDetails = errorData.details;
        } catch {
          // If JSON parse fails, try to get text
          try {
            const errorText = await response.text();
            if (errorText) {
              errorDetails = errorText;
            }
          } catch {
            // Ignore text parse errors
          }
        }

        // Show toast with different styles based on status code
        const description = errorDetails || errorMessage;
        const status = response.status;

        if (status >= 400 && status < 500) {
          // Client errors (4xx) - validation, bad request, etc. - show as warning
          toast.warning("Client Error", {
            description,
            duration: 5000,
          });
        } else if (status >= 500) {
          // Server errors (5xx) - show as error
          toast.error("Server Error", {
            description,
            duration: 5000,
          });
        } else {
          // Other HTTP errors - show as error
          toast.error("API Error", {
            description,
            duration: 5000,
          });
        }

        // Still throw error for callers that want to handle it
        const error = new Error(errorMessage);
        (error as any).status = response.status;
        (error as any).details = errorDetails;
        throw error;
      }

      return response.json();
    } catch (error) {
      // If it's not a response error (network error, etc.), show toast
      if (!(error as any).status) {
        toast.error("Network Error", {
          description: error instanceof Error ? error.message : "Failed to connect to server",
          duration: 5000,
        });
      }
      throw error;
    }
  }

  /**
   * List all banks
   */
  async listBanks() {
    return this.fetchApi<{ banks: any[] }>("/api/banks", { cache: "no-store" as RequestCache });
  }

  /**
   * Create a new bank
   */
  async createBank(bankId: string) {
    return this.fetchApi<{ bank_id: string }>("/api/banks", {
      method: "POST",
      body: JSON.stringify({ bank_id: bankId }),
    });
  }

  /**
   * Recall memories
   */
  async recall(params: {
    query: string;
    types?: string[];
    bank_id: string;
    budget?: string;
    max_tokens?: number;
    trace?: boolean;
    include?: {
      entities?: { max_tokens: number } | null;
      chunks?: { max_tokens: number } | null;
      source_facts?: { max_tokens?: number } | null;
    };
    query_timestamp?: string;
    tags?: string[];
    tags_match?: "any" | "all" | "any_strict" | "all_strict";
  }) {
    return this.fetchApi("/api/recall", {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  /**
   * Reflect and generate answer
   */
  async reflect(params: {
    query: string;
    bank_id: string;
    budget?: string;
    max_tokens?: number;
    include_facts?: boolean;
    include_tool_calls?: boolean;
    tags?: string[];
    tags_match?: "any" | "all" | "any_strict" | "all_strict";
  }) {
    return this.fetchApi<ReflectResponse>("/api/reflect", {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  async submitReflect(params: {
    query: string;
    bank_id: string;
    budget?: string;
    max_tokens?: number;
    include_facts?: boolean;
    include_tool_calls?: boolean;
    response_schema?: Record<string, any>;
    tags?: string[];
    tags_match?: "any" | "all" | "any_strict" | "all_strict";
  }) {
    return this.fetchApi<{
      operation_id: string;
      status: string;
    }>("/api/reflect/submit", {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  /**
   * Retain memories (batch)
   */
  async retain(params: {
    bank_id: string;
    items: Array<{
      content: string;
      timestamp?: string;
      context?: string;
      document_id?: string;
      metadata?: Record<string, string>;
      entities?: Array<{ text: string; type?: string }>;
      tags?: string[];
      observation_scopes?: "per_tag" | "combined" | "all_combinations" | string[][];
    }>;
    document_id?: string;
    async?: boolean;
  }) {
    const endpoint = params.async ? "/api/memories/retain_async" : "/api/memories/retain";
    return this.fetchApi<{ message?: string }>(endpoint, {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  /**
   * Get bank statistics
   */
  async getBankStats(bankId: string) {
    return this.fetchApi(`/api/stats/${bankId}`);
  }

  async getBenchmark(mode: "deterministic" | "live-api" = "live-api") {
    return this.fetchApi<BenchmarkResponse>(`/api/benchmark?mode=${mode}`, {
      cache: "no-store" as RequestCache,
    });
  }

  async runBenchmark(mode: "deterministic" | "live-api" = "live-api") {
    return this.fetchApi<BenchmarkResponse>("/api/benchmark", {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
  }

  /**
   * Get graph data
   */
  async getGraph(params: {
    bank_id: string;
    type?: string;
    limit?: number;
    q?: string;
    tags?: string[];
  }) {
    const queryParams = new URLSearchParams();
    queryParams.append("bank_id", params.bank_id);
    if (params.type) queryParams.append("type", params.type);
    if (params.limit) queryParams.append("limit", params.limit.toString());
    if (params.q) queryParams.append("q", params.q);
    if (params.tags && params.tags.length > 0) {
      params.tags.forEach((tag) => queryParams.append("tags", tag));
    }
    return this.fetchApi(`/api/graph?${queryParams}`);
  }

  async getGraphIntelligence(params: {
    bank_id: string;
    type?: string;
    limit?: number;
    q?: string;
    tags?: string[];
    tags_match?: "any" | "all" | "any_strict" | "all_strict";
    confidence_min?: number;
    node_kind?: "all" | "entity" | "topic";
    window_days?: number;
  }) {
    const queryParams = new URLSearchParams();
    queryParams.append("bank_id", params.bank_id);
    if (params.type) queryParams.append("type", params.type);
    if (params.limit) queryParams.append("limit", params.limit.toString());
    if (params.q) queryParams.append("q", params.q);
    if (params.tags_match) queryParams.append("tags_match", params.tags_match);
    if (params.confidence_min !== undefined) {
      queryParams.append("confidence_min", String(params.confidence_min));
    }
    if (params.node_kind) queryParams.append("node_kind", params.node_kind);
    if (params.window_days !== undefined)
      queryParams.append("window_days", String(params.window_days));
    if (params.tags && params.tags.length > 0) {
      params.tags.forEach((tag) => queryParams.append("tags", tag));
    }
    return this.fetchApi<GraphIntelligenceResponse>(`/api/graph/intelligence?${queryParams}`);
  }

  async investigateGraph(params: {
    bank_id: string;
    query: string;
    type?: string;
    tags?: string[];
    tags_match?: "any" | "all" | "any_strict" | "all_strict";
    confidence_min?: number;
    node_kind?: "all" | "entity" | "topic";
    window_days?: number;
    limit?: number;
  }) {
    return this.fetchApi<GraphInvestigationResponse>("/api/graph/investigate", {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  async getGraphSummary(params: {
    bank_id: string;
    surface: "state" | "evidence";
    type?: string;
    q?: string;
    tags?: string[];
    tags_match?: "any" | "all" | "any_strict" | "all_strict";
    confidence_min?: number;
    node_kind?: "all" | "entity" | "topic";
    window_days?: number;
  }) {
    const queryParams = new URLSearchParams();
    queryParams.append("bank_id", params.bank_id);
    queryParams.append("surface", params.surface);
    if (params.type) queryParams.append("type", params.type);
    if (params.q) queryParams.append("q", params.q);
    if (params.tags_match) queryParams.append("tags_match", params.tags_match);
    if (params.confidence_min !== undefined)
      queryParams.append("confidence_min", String(params.confidence_min));
    if (params.node_kind) queryParams.append("node_kind", params.node_kind);
    if (params.window_days !== undefined)
      queryParams.append("window_days", String(params.window_days));
    if (params.tags?.length) {
      params.tags.forEach((tag) => queryParams.append("tags", tag));
    }
    return this.fetchApi<GraphSummaryResponse>(`/api/graph/summary?${queryParams.toString()}`);
  }

  async getGraphNeighborhood(params: {
    bank_id: string;
    surface: "state" | "evidence";
    type?: string;
    q?: string;
    tags?: string[];
    tags_match?: "any" | "all" | "any_strict" | "all_strict";
    confidence_min?: number;
    node_kind?: "all" | "entity" | "topic";
    window_days?: number;
    focus_ids?: string[];
    depth?: number;
    limit_nodes?: number;
    limit_edges?: number;
  }) {
    const queryParams = new URLSearchParams();
    queryParams.append("bank_id", params.bank_id);
    queryParams.append("surface", params.surface);
    if (params.type) queryParams.append("type", params.type);
    if (params.q) queryParams.append("q", params.q);
    if (params.tags_match) queryParams.append("tags_match", params.tags_match);
    if (params.confidence_min !== undefined)
      queryParams.append("confidence_min", String(params.confidence_min));
    if (params.node_kind) queryParams.append("node_kind", params.node_kind);
    if (params.window_days !== undefined)
      queryParams.append("window_days", String(params.window_days));
    if (params.depth !== undefined) queryParams.append("depth", String(params.depth));
    if (params.limit_nodes !== undefined)
      queryParams.append("limit_nodes", String(params.limit_nodes));
    if (params.limit_edges !== undefined)
      queryParams.append("limit_edges", String(params.limit_edges));
    if (params.tags?.length) {
      params.tags.forEach((tag) => queryParams.append("tags", tag));
    }
    if (params.focus_ids?.length) {
      params.focus_ids.forEach((id) => queryParams.append("focus_ids", id));
    }
    return this.fetchApi<GraphNeighborhoodResponse>(
      `/api/graph/neighborhood?${queryParams.toString()}`
    );
  }

  /**
   * List operations with optional filtering and pagination
   */
  async listOperations(
    bankId: string,
    options?: { status?: string; type?: string; limit?: number; offset?: number }
  ) {
    const params = new URLSearchParams();
    if (options?.status) params.append("status", options.status);
    if (options?.type) params.append("type", options.type);
    if (options?.limit) params.append("limit", options.limit.toString());
    if (options?.offset) params.append("offset", options.offset.toString());
    const query = params.toString();
    return this.fetchApi<{
      bank_id: string;
      total: number;
      limit: number;
      offset: number;
      operations: Array<{
        id: string;
        task_type: string;
        items_count: number;
        document_id: string | null;
        created_at: string;
        status: string;
        error_message: string | null;
      }>;
    }>(`/api/operations/${bankId}${query ? `?${query}` : ""}`);
  }

  /**
   * Cancel a pending operation
   */
  async cancelOperation(bankId: string, operationId: string) {
    return this.fetchApi<{
      success: boolean;
      message: string;
      operation_id: string;
    }>(`/api/operations/${bankId}?operation_id=${operationId}`, {
      method: "DELETE",
    });
  }

  /**
   * List entities
   */
  async listEntities(params: { bank_id: string; limit?: number; offset?: number }) {
    const queryParams = new URLSearchParams();
    queryParams.append("bank_id", params.bank_id);
    if (params.limit) queryParams.append("limit", params.limit.toString());
    if (params.offset) queryParams.append("offset", params.offset.toString());
    return this.fetchApi<{
      items: any[];
      total: number;
      limit: number;
      offset: number;
    }>(`/api/entities?${queryParams}`);
  }

  /**
   * Get entity details
   */
  async getEntity(entityId: string, bankId: string) {
    return this.fetchApi(`/api/entities/${entityId}?bank_id=${bankId}`);
  }

  /**
   * Regenerate entity observations
   */
  async regenerateEntityObservations(entityId: string, bankId: string) {
    return this.fetchApi(`/api/entities/${entityId}/regenerate?bank_id=${bankId}`, {
      method: "POST",
    });
  }

  /**
   * List documents
   */
  async listDocuments(params: { bank_id: string; q?: string; limit?: number; offset?: number }) {
    const queryParams = new URLSearchParams();
    queryParams.append("bank_id", params.bank_id);
    if (params.q) queryParams.append("q", params.q);
    if (params.limit) queryParams.append("limit", params.limit.toString());
    if (params.offset) queryParams.append("offset", params.offset.toString());
    return this.fetchApi(`/api/documents?${queryParams}`);
  }

  /**
   * Get document
   */
  async getDocument(documentId: string, bankId: string) {
    return this.fetchApi(`/api/documents/${documentId}?bank_id=${bankId}`);
  }

  /**
   * Delete document and all its associated memory units
   */
  async deleteDocument(documentId: string, bankId: string) {
    return this.fetchApi<{
      success: boolean;
      message: string;
      document_id: string;
      memory_units_deleted: number;
    }>(`/api/documents/${documentId}?bank_id=${bankId}`, {
      method: "DELETE",
    });
  }

  /**
   * Delete an entire memory bank and all its data
   */
  async deleteBank(bankId: string) {
    return this.fetchApi<{
      success: boolean;
      message: string;
      deleted_count: number;
    }>(`/api/banks/${bankId}`, {
      method: "DELETE",
    });
  }

  /**
   * Clear all observations for a bank
   */
  async clearObservations(bankId: string) {
    return this.fetchApi<{
      success: boolean;
      message: string;
      deleted_count: number;
    }>(`/api/banks/${bankId}/observations`, {
      method: "DELETE",
    });
  }

  /**
   * Trigger consolidation for a bank
   */
  async triggerConsolidation(bankId: string) {
    return this.fetchApi<{
      operation_id: string;
      deduplicated: boolean;
    }>(`/api/banks/${bankId}/consolidate`, {
      method: "POST",
    });
  }

  async triggerDreamGeneration(
    bankId: string,
    params?: { trigger_source?: "manual" | "event" | "cron"; run_type?: "dream" | "trance" }
  ) {
    return this.fetchApi<{
      operation_id: string;
      deduplicated: boolean;
    }>(`/api/banks/${bankId}/dreams/trigger`, {
      method: "POST",
      body: JSON.stringify(params || {}),
    });
  }

  async listDreamArtifacts(bankId: string, limit = 20) {
    const response = await this.fetchApi<{ items: Partial<DreamArtifact>[] }>(
      `/api/banks/${bankId}/dreams?limit=${limit}`
    );
    return {
      items: (response.items || []).map((item) => normalizeDreamArtifact(item)),
    };
  }

  async getDreamStats(bankId: string) {
    return this.fetchApi<DreamStats>(`/api/banks/${bankId}/dreams/stats`);
  }

  async reviewDreamProposal(
    bankId: string,
    proposalId: string,
    body: { action: "approve" | "reject" | "request_more_evidence"; note?: string | null }
  ) {
    return this.fetchApi<DreamPromotionProposal>(
      `/api/banks/${bankId}/dreams/proposals/${proposalId}/review`,
      {
        method: "POST",
        body: JSON.stringify(body),
      }
    );
  }

  async updateDreamPredictionOutcome(
    bankId: string,
    predictionId: string,
    body: {
      status: "confirmed" | "contradicted" | "request_more_evidence";
      note?: string | null;
      evidence_ids?: string[];
    }
  ) {
    return this.fetchApi<{
      prediction: DreamPrediction;
      outcome: DreamValidationOutcome;
    }>(`/api/banks/${bankId}/dreams/predictions/${predictionId}/outcome`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  /**
   * Get chunk
   */
  async getChunk(chunkId: string) {
    return this.fetchApi(`/api/chunks/${chunkId}`);
  }

  /**
   * Get a single memory by ID
   */
  async getMemory(memoryId: string, bankId: string) {
    return this.fetchApi<{
      id: string;
      text: string;
      context: string;
      date: string;
      type: string;
      mentioned_at: string | null;
      occurred_start: string | null;
      occurred_end: string | null;
      entities: string[];
      document_id: string | null;
      chunk_id: string | null;
      tags: string[];
      observation_scopes: string | string[][] | null;
      history?: {
        previous_text: string;
        previous_tags: string[];
        previous_occurred_start: string | null;
        previous_occurred_end: string | null;
        previous_mentioned_at: string | null;
        changed_at: string;
        new_source_memory_ids: string[];
      }[];
    }>(`/api/memories/${memoryId}?bank_id=${bankId}`);
  }

  /**
   * Get the history of an observation with resolved source facts
   */
  async getObservationHistory(memoryId: string, bankId: string) {
    return this.fetchApi<
      {
        previous_text: string;
        previous_tags: string[];
        previous_occurred_start: string | null;
        previous_occurred_end: string | null;
        previous_mentioned_at: string | null;
        changed_at: string;
        new_source_memory_ids: string[];
        source_facts: {
          id: string;
          text: string | null;
          type: string | null;
          context: string | null;
          is_new: boolean;
        }[];
      }[]
    >(`/api/memories/${memoryId}/history?bank_id=${bankId}`);
  }

  /**
   * Get bank profile
   */
  async getBankProfile(bankId: string) {
    return this.fetchApi<{
      bank_id: string;
      name: string;
      disposition: {
        skepticism: number;
        literalism: number;
        empathy: number;
      };
      mission: string;
      background?: string; // Deprecated, kept for backwards compatibility
    }>(`/api/profile/${bankId}`);
  }

  /**
   * Set bank mission
   */
  async setBankMission(bankId: string, mission: string) {
    return this.fetchApi(`/api/banks/${bankId}`, {
      method: "PATCH",
      body: JSON.stringify({ mission }),
    });
  }

  /**
   * List directives for a bank
   */
  async listDirectives(bankId: string, tags?: string[], tagsMatch?: string) {
    const params = new URLSearchParams();
    if (tags && tags.length > 0) {
      tags.forEach((t) => params.append("tags", t));
    }
    if (tagsMatch) {
      params.append("tags_match", tagsMatch);
    }
    const query = params.toString();
    return this.fetchApi<{
      items: Array<{
        id: string;
        bank_id: string;
        name: string;
        content: string;
        priority: number;
        is_active: boolean;
        tags: string[];
        created_at: string;
        updated_at: string;
      }>;
    }>(`/api/banks/${bankId}/directives${query ? `?${query}` : ""}`);
  }

  /**
   * Create a directive
   */
  async createDirective(
    bankId: string,
    params: {
      name: string;
      content: string;
      priority?: number;
      is_active?: boolean;
      tags?: string[];
    }
  ) {
    return this.fetchApi<{
      id: string;
      bank_id: string;
      name: string;
      content: string;
      priority: number;
      is_active: boolean;
      tags: string[];
      created_at: string;
      updated_at: string;
    }>(`/api/banks/${bankId}/directives`, {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  /**
   * Get a directive
   */
  async getDirective(bankId: string, directiveId: string) {
    return this.fetchApi<{
      id: string;
      bank_id: string;
      name: string;
      content: string;
      priority: number;
      is_active: boolean;
      tags: string[];
      created_at: string;
      updated_at: string;
    }>(`/api/banks/${bankId}/directives/${directiveId}`);
  }

  /**
   * Delete a directive
   */
  async deleteDirective(bankId: string, directiveId: string) {
    return this.fetchApi(`/api/banks/${bankId}/directives/${directiveId}`, {
      method: "DELETE",
    });
  }

  /**
   * Update a directive
   */
  async updateDirective(
    bankId: string,
    directiveId: string,
    params: {
      name?: string;
      content?: string;
      priority?: number;
      is_active?: boolean;
      tags?: string[];
    }
  ) {
    return this.fetchApi<{
      id: string;
      bank_id: string;
      name: string;
      content: string;
      priority: number;
      is_active: boolean;
      tags: string[];
      created_at: string;
      updated_at: string;
    }>(`/api/banks/${bankId}/directives/${directiveId}`, {
      method: "PATCH",
      body: JSON.stringify(params),
    });
  }

  /**
   * Get operation status
   */
  async getOperationStatus(bankId: string, operationId: string) {
    return this.fetchApi<OperationStatus>(`/api/banks/${bankId}/operations/${operationId}`);
  }

  /**
   * Get the final result for an async operation
   */
  async getOperationResult(bankId: string, operationId: string) {
    return this.fetchApi<OperationResult>(`/api/banks/${bankId}/operations/${operationId}/result`);
  }

  /**
   * Update bank profile
   */
  async updateBankProfile(
    bankId: string,
    profile: {
      name?: string;
      disposition?: {
        skepticism: number;
        literalism: number;
        empathy: number;
      };
      mission?: string;
    }
  ) {
    return this.fetchApi(`/api/profile/${bankId}`, {
      method: "PUT",
      body: JSON.stringify(profile),
    });
  }

  // ============= OBSERVATIONS (auto-consolidated, read-only) =============

  /**
   * List observations for a bank (auto-consolidated knowledge)
   */
  async listObservations(bankId: string, tags?: string[], tagsMatch?: string) {
    const params = new URLSearchParams();
    if (tags && tags.length > 0) {
      tags.forEach((t) => params.append("tags", t));
    }
    if (tagsMatch) {
      params.append("tags_match", tagsMatch);
    }
    const query = params.toString();
    return this.fetchApi<{
      items: Array<{
        id: string;
        bank_id: string;
        text: string;
        proof_count: number;
        history: Array<{
          previous_text: string;
          changed_at: string;
          reason: string;
        }>;
        tags: string[];
        source_memory_ids: string[];
        source_memories: Array<{
          id: string;
          text: string;
          type: string;
          context?: string;
          occurred_start?: string;
          mentioned_at?: string;
        }>;
        created_at: string;
        updated_at: string;
      }>;
    }>(`/api/banks/${bankId}/observations${query ? `?${query}` : ""}`);
  }

  /**
   * Get an observation with source memories
   */
  async getObservation(bankId: string, observationId: string) {
    return this.fetchApi<{
      id: string;
      bank_id: string;
      text: string;
      proof_count: number;
      history: Array<{
        previous_text: string;
        changed_at: string;
        reason: string;
      }>;
      tags: string[];
      source_memory_ids: string[];
      source_memories: Array<{
        id: string;
        text: string;
        type: string;
        context?: string;
        occurred_start?: string;
        mentioned_at?: string;
      }>;
      created_at: string;
      updated_at: string;
    }>(`/api/banks/${bankId}/observations/${observationId}`);
  }

  // ============= MENTAL MODELS (stored reflect responses) =============

  /**
   * List mental models for a bank
   */
  async listMentalModels(bankId: string, tags?: string[], tagsMatch?: string) {
    const params = new URLSearchParams();
    if (tags && tags.length > 0) {
      tags.forEach((t) => params.append("tags", t));
    }
    if (tagsMatch) {
      params.append("tags_match", tagsMatch);
    }
    const query = params.toString();
    return this.fetchApi<{
      items: Array<{
        id: string;
        bank_id: string;
        name: string;
        source_query: string;
        content: string;
        tags: string[];
        max_tokens: number;
        trigger: { refresh_after_consolidation: boolean };
        last_refreshed_at: string;
        created_at: string;
        reflect_response?: {
          text: string;
          based_on: Record<string, Array<{ id: string; text: string; type: string }>>;
        };
      }>;
    }>(`/api/banks/${bankId}/mental-models${query ? `?${query}` : ""}`);
  }

  /**
   * Create a mental model (async - content auto-generated in background)
   * Returns operation_id to track progress
   */
  async createMentalModel(
    bankId: string,
    params: {
      id?: string;
      name: string;
      source_query: string;
      tags?: string[];
      max_tokens?: number;
      trigger?: { refresh_after_consolidation: boolean };
    }
  ) {
    return this.fetchApi<{
      operation_id: string;
    }>(`/api/banks/${bankId}/mental-models`, {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  /**
   * Get a mental model
   */
  async getMentalModel(bankId: string, mentalModelId: string): Promise<MentalModel> {
    return this.fetchApi<MentalModel>(`/api/banks/${bankId}/mental-models/${mentalModelId}`);
  }

  /**
   * Update a mental model
   */
  async updateMentalModel(
    bankId: string,
    mentalModelId: string,
    params: {
      name?: string;
      source_query?: string;
      max_tokens?: number;
      tags?: string[];
      trigger?: { refresh_after_consolidation: boolean };
    }
  ) {
    return this.fetchApi<{
      id: string;
      bank_id: string;
      name: string;
      source_query: string;
      content: string;
      tags: string[];
      max_tokens: number;
      trigger: { refresh_after_consolidation: boolean };
      last_refreshed_at: string;
      created_at: string;
      reflect_response?: {
        text: string;
        based_on: Record<string, Array<{ id: string; text: string; type: string }>>;
      };
    }>(`/api/banks/${bankId}/mental-models/${mentalModelId}`, {
      method: "PATCH",
      body: JSON.stringify(params),
    });
  }

  /**
   * Delete a mental model
   */
  async deleteMentalModel(bankId: string, mentalModelId: string) {
    return this.fetchApi(`/api/banks/${bankId}/mental-models/${mentalModelId}`, {
      method: "DELETE",
    });
  }

  /**
   * Refresh a mental model (re-run source query) - async operation
   */
  async refreshMentalModel(bankId: string, mentalModelId: string) {
    return this.fetchApi<{
      operation_id: string;
    }>(`/api/banks/${bankId}/mental-models/${mentalModelId}/refresh`, {
      method: "POST",
    });
  }

  /**
   * Get the refresh history of a mental model
   */
  async getMentalModelHistory(bankId: string, mentalModelId: string) {
    return this.fetchApi<
      {
        previous_content: string | null;
        changed_at: string;
      }[]
    >(`/api/banks/${bankId}/mental-models/${mentalModelId}/history`);
  }

  /**
   * Get API version and feature flags
   * Use this to check which capabilities are available in the dataplane
   */
  async getVersion() {
    return this.fetchApi<{
      api_version: string;
      features: {
        observations: boolean;
        mcp: boolean;
        worker: boolean;
        bank_config_api: boolean;
        file_upload_api: boolean;
        brain_runtime: boolean;
        sub_routine: boolean;
        brain_import_export: boolean;
      };
    }>("/api/version");
  }

  async triggerSubRoutine(
    bankId: string,
    params?: {
      mode?: "warmup" | "incremental" | "full_copy";
      horizon_hours?: number;
      force_rebuild?: boolean;
    }
  ) {
    return this.fetchApi<{
      operation_id: string;
      deduplicated: boolean;
    }>(`/api/banks/${bankId}/sub-routine`, {
      method: "POST",
      body: JSON.stringify(params || {}),
    });
  }

  async getBrainStatus(bankId: string) {
    return this.fetchApi<{
      enabled: boolean;
      circuit_open: boolean;
      failure_count: number;
      bank_id: string;
      file_path: string;
      exists: boolean;
      size_bytes: number;
      last_modified_at: string | null;
      source_snapshot_id: string | null;
      generated_at: string | null;
      native_library_loaded: boolean;
      format_version: number | null;
      model_signature: string | null;
      compatibility_reason: string | null;
      metrics: Record<string, number>;
    }>(`/api/banks/${bankId}/brain/status`);
  }

  async getSubRoutinePredictions(bankId: string, horizonHours = 24) {
    return this.fetchApi<{
      bank_id: string;
      horizon_hours: number;
      predictions: Array<{ hour_utc: number; score: number }>;
      sample_count: number;
      source_snapshot_id: string | null;
      model_signature: string | null;
    }>(`/api/banks/${bankId}/sub-routine/predictions?horizon_hours=${horizonHours}`);
  }

  async getSubRoutineHistogram(bankId: string) {
    return this.fetchApi<{
      bank_id: string;
      histogram: Array<{ hour_utc: number; score: number }>;
      sample_count: number;
      source_snapshot_id: string | null;
      model_signature: string | null;
    }>(`/api/banks/${bankId}/sub-routine/histogram`);
  }

  async getBrainInfluence(
    bankId: string,
    params?: {
      window_days?: number;
      top_k?: number;
      entity_type?: "all" | "memory" | "chunk" | "mental_model";
    }
  ) {
    const qs = new URLSearchParams();
    if (params?.window_days) qs.set("window_days", String(params.window_days));
    if (params?.top_k) qs.set("top_k", String(params.top_k));
    if (params?.entity_type) qs.set("entity_type", params.entity_type);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return this.fetchApi<{
      bank_id: string;
      window_days: number;
      entity_type: string;
      leaderboard: Array<{
        id: string;
        type: string;
        text: string;
        access_count: number;
        influence_score: number;
        contribution: {
          recency: number;
          freq: number;
          graph: number;
          rerank: number;
          dream: number;
        };
        last_accessed_at: string | null;
      }>;
      heatmap: Array<{ weekday: number; hour_utc: number; count: number; score: number }>;
      trend: Array<{ index: number; raw: number; ewma: number; lower: number; upper: number }>;
      anomalies: Array<{ index: number; score: number; zscore: number; iqr?: boolean }>;
      summary: Record<string, unknown>;
    }>(`/api/banks/${bankId}/brain/influence${suffix}`);
  }

  async validateBrainImport(bankId: string, file: File) {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`/api/banks/${bankId}/brain/import/validate`, {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `HTTP ${response.status}`);
    }
    return response.json() as Promise<{
      valid: boolean;
      version: number | null;
      reason: string | null;
    }>;
  }

  async importBrainFile(bankId: string, file: File) {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`/api/banks/${bankId}/brain/import`, {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `HTTP ${response.status}`);
    }
    return response.json() as Promise<{
      bank_id: string;
      file_path: string;
      size_bytes: number;
      format_version: number | null;
    }>;
  }

  async exportBrainFile(bankId: string): Promise<Blob> {
    const response = await fetch(`/api/banks/${bankId}/brain/export`, {
      method: "GET",
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `HTTP ${response.status}`);
    }
    return response.blob();
  }

  async learnFromRemoteBrain(
    bankId: string,
    params: {
      remote_endpoint: string;
      remote_bank_id: string;
      remote_api_key?: string;
      learning_type?: "auto" | "distilled" | "structured" | "raw_mirror";
      mode?: "incremental" | "full_copy";
    }
  ) {
    return this.fetchApi<{ operation_id: string; deduplicated: boolean }>(
      `/api/banks/${bankId}/brain/learn`,
      {
        method: "POST",
        body: JSON.stringify(params),
      }
    );
  }

  async fetchRemoteBanks(params: { remote_endpoint: string; remote_api_key?: string }) {
    return this.fetchApi<{ banks: Array<{ bank_id: string }> }>(`/api/brain/remote-banks`, {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  async probeRemoteCapabilities(params: {
    remote_endpoint: string;
    remote_bank_id: string;
    remote_api_key?: string;
  }) {
    return this.fetchApi<{
      capabilities: {
        version_ok: boolean;
        banks_ok: boolean;
        brain_export_ok: boolean;
        mental_models_ok: boolean;
        memories_ok: boolean;
        entities_ok: boolean;
        status_codes: Record<string, number | null>;
      };
      recommended_learning_type: "distilled" | "structured" | "raw_mirror" | "auto";
    }>(`/api/brain/remote-capabilities`, {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  /**
   * Upload files for retain (uses file conversion API)
   * Requires file_upload_api feature flag to be enabled
   * Converter is configured server-side via ATULYA_API_FILE_CONVERTER
   */
  async uploadFiles(params: {
    bank_id: string;
    files: File[];
    document_tags?: string[];
    async?: boolean;
    files_metadata?: Array<{
      document_id?: string;
      context?: string;
      metadata?: Record<string, any>;
      tags?: string[];
      timestamp?: string;
    }>;
  }) {
    const formData = new FormData();

    // Add files
    params.files.forEach((file) => {
      formData.append("files", file);
    });

    // Add request JSON (including bank_id)
    const requestData: any = {
      bank_id: params.bank_id,
      async: params.async ?? true,
    };
    if (params.document_tags) requestData.document_tags = params.document_tags;
    if (params.files_metadata) requestData.files_metadata = params.files_metadata;

    formData.append("request", JSON.stringify(requestData));

    // Use fetch directly for multipart/form-data
    const response = await fetch(`/api/files/retain`, {
      method: "POST",
      body: formData,
      // Don't set Content-Type - browser will set it with boundary
    });

    if (!response.ok) {
      let errorMessage = `HTTP ${response.status}`;
      try {
        const errorData = await response.json();
        errorMessage = errorData.error || errorMessage;
      } catch {
        // Ignore parse errors
      }
      const error = new Error(errorMessage);
      (error as any).status = response.status;
      throw error;
    }

    return response.json();
  }

  /**
   * Get bank configuration (resolved with hierarchy)
   */
  async getBankConfig(bankId: string) {
    return this.fetchApi<{
      bank_id: string;
      config: Record<string, any>;
      overrides: Record<string, any>;
    }>(`/api/banks/${bankId}/config`);
  }

  /**
   * Update bank configuration overrides
   */
  async updateBankConfig(bankId: string, updates: Record<string, any>) {
    return this.fetchApi<{
      bank_id: string;
      config: Record<string, any>;
      overrides: Record<string, any>;
    }>(`/api/banks/${bankId}/config`, {
      method: "PATCH",
      body: JSON.stringify({ updates }),
    });
  }

  /**
   * Reset bank configuration to defaults
   */
  async resetBankConfig(bankId: string) {
    return this.fetchApi<{
      bank_id: string;
      config: Record<string, any>;
      overrides: Record<string, any>;
    }>(`/api/banks/${bankId}/config`, {
      method: "DELETE",
    });
  }

  /**
   * List webhooks for a bank
   */
  async listWebhooks(bankId: string): Promise<{ items: Webhook[] }> {
    return this.fetchApi<{ items: Webhook[] }>(`/api/banks/${bankId}/webhooks`);
  }

  /**
   * Create a webhook
   */
  async createWebhook(
    bankId: string,
    params: {
      url: string;
      secret?: string;
      event_types?: string[];
      enabled?: boolean;
      http_config?: WebhookHttpConfig;
    }
  ): Promise<Webhook> {
    return this.fetchApi<Webhook>(`/api/banks/${bankId}/webhooks`, {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  /**
   * Update a webhook (PATCH — only provided fields are changed)
   */
  async updateWebhook(
    bankId: string,
    webhookId: string,
    params: {
      url?: string;
      secret?: string | null;
      event_types?: string[];
      enabled?: boolean;
      http_config?: WebhookHttpConfig;
    }
  ): Promise<Webhook> {
    return this.fetchApi<Webhook>(`/api/banks/${bankId}/webhooks/${webhookId}`, {
      method: "PATCH",
      body: JSON.stringify(params),
    });
  }

  /**
   * Delete a webhook
   */
  async deleteWebhook(bankId: string, webhookId: string): Promise<{ success: boolean }> {
    return this.fetchApi<{ success: boolean }>(`/api/banks/${bankId}/webhooks/${webhookId}`, {
      method: "DELETE",
    });
  }

  /**
   * List webhook deliveries
   */
  async listWebhookDeliveries(
    bankId: string,
    webhookId: string,
    limit?: number,
    cursor?: string
  ): Promise<{ items: WebhookDelivery[]; next_cursor: string | null }> {
    const params = new URLSearchParams();
    if (limit) params.append("limit", limit.toString());
    if (cursor) params.append("cursor", cursor);
    const query = params.toString();
    return this.fetchApi<{ items: WebhookDelivery[]; next_cursor: string | null }>(
      `/api/banks/${bankId}/webhooks/${webhookId}/deliveries${query ? `?${query}` : ""}`
    );
  }
}

// Export singleton instance
export const client = new ControlPlaneClient();
