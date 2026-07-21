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
  created_at: string | null;
  updated_at: string | null;
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
