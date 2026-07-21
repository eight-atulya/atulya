/**
 * Shared request-aware dataplane client helpers for the control plane.
 * User-scoped calls must always bind credentials to the incoming request.
 */

import { createClient, createConfig, sdk } from "@eight-atulya/atulya-client";
import type { NextRequest } from "next/server";

export const DATAPLANE_URL = process.env.ATULYA_CP_DATAPLANE_API_URL || "http://localhost:8888";
const DATAPLANE_API_KEY = process.env.ATULYA_CP_DATAPLANE_API_KEY || "";
const ALLOW_DATAPLANE_API_KEY_FALLBACK =
  process.env.NODE_ENV !== "production" &&
  process.env.ATULYA_CP_ALLOW_DATAPLANE_API_KEY_FALLBACK !== "false";
export const ATULYA_SESSION_COOKIE = "atulya_session";

function authHeaderForToken(token?: string | null): Record<string, string> {
  const resolved = token || (ALLOW_DATAPLANE_API_KEY_FALLBACK ? DATAPLANE_API_KEY : "");
  return resolved ? { Authorization: `Bearer ${resolved}` } : {};
}

function authHeaderForRequest(request: Request | NextRequest): Record<string, string> {
  const authorization = request.headers.get("authorization")?.trim();
  if (authorization) return { Authorization: authorization };

  const cookieHeader = request.headers.get("cookie") || "";
  const cookie = cookieHeader
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${ATULYA_SESSION_COOKIE}=`));

  if (cookie) {
    const rawToken = cookie.slice(ATULYA_SESSION_COOKIE.length + 1);
    try {
      return authHeaderForToken(decodeURIComponent(rawToken));
    } catch {
      return {};
    }
  }

  return authHeaderForToken();
}

export function getDataplaneHeadersForRequest(
  request: Request | NextRequest,
  extra?: Record<string, string>
): Record<string, string> {
  return { ...authHeaderForRequest(request), ...extra };
}

export function createLowLevelClientForRequest(request: Request | NextRequest) {
  return createClient(
    createConfig({
      baseUrl: DATAPLANE_URL,
      headers: getDataplaneHeadersForRequest(request),
    })
  );
}

/**
 * Export SDK functions for direct API access
 */
export { sdk };
