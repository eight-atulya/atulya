/**
 * Admin API client — server-side only.
 *
 * NEVER import this in a "use client" component.
 * Platform calls forward the signed-in actor's HTTP-only session.
 */

const DATAPLANE_URL = process.env.ATULYA_CP_DATAPLANE_API_URL || "http://localhost:8888";

/**
 * Typed fetch wrapper for all /v1/platform/* endpoints.
 * Throws on non-2xx responses with the server's error detail.
 */
export async function adminFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const { canUsePlatformAdmin, getCurrentIdentity, getSessionToken } =
    await import("@/lib/server-auth");
  const identity = await getCurrentIdentity();
  if (!canUsePlatformAdmin(identity)) {
    throw new Error("Access denied: missing system.admin on system:*");
  }
  const token = await getSessionToken();
  if (!token) throw new Error("Authentication session missing");

  const url = `${DATAPLANE_URL}/v1/platform${path}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
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
    if (res.status === 404 && detail === "Not Found") {
      detail =
        "Platform routes are not mounted. Enable database auth and admin routes on the API, then restart it.";
    }
    throw new Error(`Admin API error (${path}): ${detail}`);
  }

  return res.json() as Promise<T>;
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

export interface OrgResponse {
  id: string;
  slug: string;
  name: string;
  schema_name: string;
  status: string;
  created_at: string;
}

export interface PrincipalResponse {
  id: string;
  org_id: string;
  email: string | null;
  display_name: string;
  principal_type: string;
  role: string;
  status: string;
  created_at: string;
}

export interface AccessGrantResponse {
  id: string;
  org_id: string;
  subject_type: string;
  subject_id: string;
  action: string;
  scope_type: string;
  scope_id: string;
  created_at: string;
}

export interface AuditEventResponse {
  id: string;
  org_id: string | null;
  actor_principal_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  result: string;
  metadata: Record<string, unknown>;
  created_at: string;
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
  principal_id?: string | null;
  key_prefix?: string | null;
  last_used_at?: string | null;
  description?: string | null;
  raw_key?: string; // Only present on creation
}
