/**
 * Shared Atulya API client instance for the control plane.
 * Configured to connect to the dataplane API server.
 */

import {
  AtulyaClient,
  AtulyaError,
  createClient,
  createConfig,
  sdk,
} from "@eight-atulya/atulya-client";
import type { NextRequest } from "next/server";

export const DATAPLANE_URL = process.env.ATULYA_CP_DATAPLANE_API_URL || "http://localhost:8888";
const DATAPLANE_API_KEY = process.env.ATULYA_CP_DATAPLANE_API_KEY || "";
export const ATULYA_SESSION_COOKIE = "atulya_session";

function authHeaderForToken(token?: string | null): Record<string, string> {
  const resolved = token || DATAPLANE_API_KEY;
  return resolved ? { Authorization: `Bearer ${resolved}` } : {};
}

/**
 * Auth headers for direct fetch calls to the dataplane API.
 */
export function getDataplaneHeaders(extra?: Record<string, string>): Record<string, string> {
  return { ...authHeaderForToken(), ...extra };
}

export function getDataplaneHeadersForRequest(
  request: Request | NextRequest,
  extra?: Record<string, string>
): Record<string, string> {
  const cookieHeader = request.headers.get("cookie") || "";
  const token = cookieHeader
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${ATULYA_SESSION_COOKIE}=`))
    ?.slice(ATULYA_SESSION_COOKIE.length + 1);
  return { ...authHeaderForToken(token ? decodeURIComponent(token) : undefined), ...extra };
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
 * High-level client with convenience methods
 */
export const atulyaClient = new AtulyaClient({
  baseUrl: DATAPLANE_URL,
  apiKey: DATAPLANE_API_KEY || undefined,
});

/**
 * Low-level client for direct SDK access
 */
export const lowLevelClient = createClient(
  createConfig({
    baseUrl: DATAPLANE_URL,
    headers: DATAPLANE_API_KEY ? { Authorization: `Bearer ${DATAPLANE_API_KEY}` } : undefined,
  })
);

/**
 * Export SDK functions for direct API access
 */
export { sdk };

/**
 * Export AtulyaError for error handling
 */
export { AtulyaError };
