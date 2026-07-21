import "server-only";

import { cookies } from "next/headers";

const ATULYA_SESSION_COOKIE = "atulya_session";
const DATAPLANE_URL = process.env.ATULYA_CP_DATAPLANE_API_URL || "http://localhost:8888";

export interface CurrentIdentity {
  org_id: string | null;
  active_org_id: string | null;
  org_slug?: string | null;
  org_name?: string | null;
  schema_name: string;
  principal_id: string | null;
  email: string | null;
  display_name: string | null;
  principal_type: string | null;
  role: string;
  allowed_actions: string[] | null;
  action_scopes: Record<string, string[]> | null;
  is_superuser: boolean;
  email_verified: boolean;
  memberships: Array<{
    id: string;
    org_id: string;
    org_slug: string;
    org_name: string;
    schema_name: string;
    role_id: string;
    role: string;
    status: string;
  }>;
}

export async function getSessionToken(): Promise<string | null> {
  const cookieStore = await cookies();
  return cookieStore.get(ATULYA_SESSION_COOKIE)?.value ?? null;
}

export async function getCurrentIdentity(): Promise<CurrentIdentity | null> {
  if (process.env.ATULYA_CP_AUTH_DISABLED === "true") {
    return {
      org_id: null,
      active_org_id: null,
      schema_name: "public",
      principal_id: null,
      email: "local-dev",
      display_name: "Local Dev",
      principal_type: "user",
      role: "superuser",
      allowed_actions: ["system.admin"],
      action_scopes: { "system.admin": ["system:*"] },
      is_superuser: true,
      email_verified: true,
      memberships: [],
    };
  }

  const token = await getSessionToken();
  if (!token) return null;

  try {
    const response = await fetch(`${DATAPLANE_URL}/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as CurrentIdentity;
  } catch {
    return null;
  }
}

export function canUseAdminConsole(identity: CurrentIdentity | null): boolean {
  if (!identity) return false;
  if (identity.is_superuser || identity.role === "owner" || identity.role === "admin") return true;
  const actions = new Set(identity.allowed_actions || []);
  return (
    actions.has("system.admin") || Array.from(actions).some((action) => action.startsWith("admin."))
  );
}

export function canUsePlatformAdmin(identity: CurrentIdentity | null): boolean {
  if (!identity) return false;
  if (identity.is_superuser || identity.role === "superuser") return true;
  return (
    new Set(identity.allowed_actions || []).has("system.admin") &&
    new Set(identity.action_scopes?.["system.admin"] || []).has("system:*")
  );
}
