/**
 * Admin API client — server-side only.
 *
 * NEVER import this in a "use client" component.
 * The ATULYA_CP_ADMIN_API_KEY env var is server-only (no NEXT_PUBLIC_ prefix).
 *
 */

const DATAPLANE_URL = process.env.ATULYA_CP_DATAPLANE_API_URL || "http://localhost:8888";
const ADMIN_KEY = process.env.ATULYA_CP_ADMIN_API_KEY || "";

/**
 * Typed fetch wrapper for all /v1/admin/* endpoints.
 * Throws on non-2xx responses with the server's error detail.
 */
export async function adminFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${DATAPLANE_URL}/v1/admin${path}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${ADMIN_KEY}`,
      ...(init?.headers ?? {}),
    },
    cache: "no-store", // Admin data must always be fresh
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      /* ignore parse error */
    }
    throw new Error(`Admin API error (${path}): ${detail}`);
  }

  return res.json() as Promise<T>;
}

/** Returns true if admin API is configured (key is set). */
export function isAdminConfigured(): boolean {
  return ADMIN_KEY.length > 0;
}

// ---------------------------------------------------------------------------
// Typed response shapes — mirrors api/admin.py Pydantic models
// ---------------------------------------------------------------------------

export interface SystemHealthResponse {
  status: string;
  api_version: string;
  db_pool_min: number;
  db_pool_max: number;
  db_pool_size: number;
  db_pool_free: number;
  migration_version: string | null;
  worker_count: number;
  admin_schema: string;
}

export interface TenantSummaryResponse {
  schema_name: string;
  bank_count: number;
}

export interface WorkerStatusResponse {
  worker_id: string;
  schema_name: string;
  pending_count: number;
  stuck_count: number;
  last_seen_at: string | null;
}

export interface OperationSummaryResponse {
  operation_id: string;
  bank_id: string;
  schema_name: string;
  operation_type: string;
  status: string;
  worker_id: string | null;
  created_at: string;
  updated_at: string | null;
  error_message: string | null;
}

export interface ApiKeyResponse {
  id: string;
  name: string;
  role: string;
  schema_name: string;
  allowed_bank_ids: string[] | null;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  raw_key?: string; // Only present on creation
}
