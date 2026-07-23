/**
 * Server-side access to the active workspace's scoped bank API.
 *
 * This deliberately uses the signed-in session. It must never use the
 * platform recovery key because the dataplane performs the bank ABAC filter.
 */

import "server-only";

import { getSessionToken } from "@/lib/server-auth";

const DATAPLANE_URL = process.env.ATULYA_CP_DATAPLANE_API_URL || "http://localhost:8888";

export interface WorkspaceBank {
  bank_id: string;
  name: string | null;
  mission: string | null;
  disposition?: {
    skepticism: number;
    literalism: number;
    empathy: number;
  } | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface WorkspaceBankStats {
  bank_id: string;
  total_nodes: number;
  total_links: number;
  total_documents: number;
  pending_operations: number;
  failed_operations: number;
  last_consolidated_at: string | null;
  pending_consolidation: number;
  total_observations: number;
}

export interface WorkspaceBankSummary extends WorkspaceBank {
  stats: WorkspaceBankStats | null;
  stats_error: boolean;
}

export async function workspaceFetch<T>(path: string): Promise<T> {
  const token = await getSessionToken();
  if (!token) throw new Error("Authentication session missing");

  const suffix = path.startsWith("/") ? path : `/${path}`;
  const response = await fetch(`${DATAPLANE_URL}/v1/default${suffix}`, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
    },
    cache: "no-store",
  });

  const body = await response.text();
  let payload: unknown = null;
  if (body) {
    try {
      payload = JSON.parse(body);
    } catch {
      payload = body;
    }
  }

  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? String((payload as { detail?: unknown }).detail)
        : `HTTP ${response.status}`;
    throw new Error(detail);
  }

  return payload as T;
}

/**
 * Load the existing per-bank stats endpoint with a small concurrency cap.
 * The bank list is already ABAC-filtered, and each stats request is checked
 * again by the API, so this remains safe when membership scopes change.
 */
export async function loadWorkspaceBankSummaries(
  banks: WorkspaceBank[],
  concurrency = 4
): Promise<WorkspaceBankSummary[]> {
  if (banks.length === 0) return [];

  const summaries: WorkspaceBankSummary[] = banks.map((bank) => ({
    ...bank,
    stats: null,
    stats_error: false,
  }));
  let nextIndex = 0;

  async function loadNext(): Promise<void> {
    while (nextIndex < banks.length) {
      const index = nextIndex++;
      try {
        summaries[index].stats = await workspaceFetch<WorkspaceBankStats>(
          `/banks/${encodeURIComponent(banks[index].bank_id)}/stats`
        );
      } catch {
        // Keep the bank visible when a stats read is temporarily unavailable.
        summaries[index].stats_error = true;
      }
    }
  }

  const workerCount = Math.min(Math.max(1, concurrency), banks.length);
  await Promise.all(Array.from({ length: workerCount }, () => loadNext()));
  return summaries;
}
