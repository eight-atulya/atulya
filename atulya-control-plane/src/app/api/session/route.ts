import { NextResponse } from "next/server";
import { ATULYA_SESSION_COOKIE } from "@/lib/atulya-client";
import { getCurrentIdentity, getSessionToken } from "@/lib/server-auth";

const DATAPLANE_URL = process.env.ATULYA_CP_DATAPLANE_API_URL || "http://localhost:8888";
const ATULYA_LOGGED_OUT_COOKIE = "atulya_logged_out";

function classifyTenantProvider(extension: string) {
  if (!extension) return "default";
  if (extension.includes("supabase_tenant")) return "supabase";
  if (extension.includes("DbApiKeyTenantExtension")) return "db-api-key";
  if (extension.includes("ApiKeyTenantExtension")) return "api-key";
  if (extension.includes("SuperuserTenantExtension")) return "superuser";
  return "custom";
}

export async function GET() {
  const dataplaneApiKeyConfigured = Boolean(process.env.ATULYA_CP_DATAPLANE_API_KEY?.trim());
  const tenantExtension = process.env.ATULYA_API_TENANT_EXTENSION?.trim() || "";
  const tenantProvider = classifyTenantProvider(tenantExtension);
  const supabaseUrlConfigured = Boolean(process.env.ATULYA_API_TENANT_SUPABASE_URL?.trim());
  const identity = await getCurrentIdentity();
  const token = await getSessionToken();
  const sessions = token
    ? await fetch(`${DATAPLANE_URL}/v1/auth/sessions`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      })
        .then((response) => (response.ok ? response.json() : []))
        .catch(() => [])
    : [];

  return NextResponse.json(
    {
      user: {
        display_name:
          identity?.display_name ||
          identity?.email ||
          (dataplaneApiKeyConfigured ? "Control Plane Operator" : "Local Operator"),
        role: identity?.role || "operator",
        identity_source: identity ? "session" : "control-plane",
        email: identity?.email || null,
        workspace: identity?.org_name || identity?.org_slug || null,
        workspace_count: identity?.memberships.length || 0,
      },
      auth: {
        mode: identity ? "session" : dataplaneApiKeyConfigured ? "dataplane_api_key" : "public",
        configured: Boolean(identity) || dataplaneApiKeyConfigured,
        logout_mode: identity ? "session" : "local",
        sessions,
      },
      tenancy: {
        provider: tenantProvider,
        configured: tenantProvider !== "default",
        supabase_url_configured: supabaseUrlConfigured,
        schema_prefix: process.env.ATULYA_API_TENANT_SCHEMA_PREFIX || "user",
      },
      admin: {
        configured: Boolean(
          identity?.allowed_actions?.some(
            (action) => action === "system.admin" || action.startsWith("admin.")
          )
        ),
      },
      dataplane: {
        url: DATAPLANE_URL,
      },
    },
    { status: 200 }
  );
}

export async function POST() {
  const token = await getSessionToken();
  if (token) {
    await fetch(`${DATAPLANE_URL}/v1/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    }).catch(() => null);
  }
  const response = NextResponse.json({ ok: true, logout_mode: "session" }, { status: 200 });
  response.cookies.delete(ATULYA_SESSION_COOKIE);
  response.cookies.set(ATULYA_LOGGED_OUT_COOKIE, "1", {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
  });
  return response;
}
