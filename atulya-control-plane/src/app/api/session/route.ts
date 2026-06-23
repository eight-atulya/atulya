import { NextResponse } from "next/server";

const DATAPLANE_URL = process.env.ATULYA_CP_DATAPLANE_API_URL || "http://localhost:8888";

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
  const adminConfigured = Boolean(process.env.ATULYA_CP_ADMIN_API_KEY?.trim());
  const tenantExtension = process.env.ATULYA_API_TENANT_EXTENSION?.trim() || "";
  const tenantProvider = classifyTenantProvider(tenantExtension);
  const supabaseUrlConfigured = Boolean(process.env.ATULYA_API_TENANT_SUPABASE_URL?.trim());

  return NextResponse.json(
    {
      user: {
        display_name: dataplaneApiKeyConfigured ? "Control Plane Operator" : "Local Operator",
        role: adminConfigured ? "operator + admin" : "operator",
        identity_source: "control-plane",
      },
      auth: {
        mode: dataplaneApiKeyConfigured ? "dataplane_api_key" : "public",
        configured: dataplaneApiKeyConfigured,
        logout_mode: "local",
      },
      tenancy: {
        provider: tenantProvider,
        configured: tenantProvider !== "default",
        supabase_url_configured: supabaseUrlConfigured,
        schema_prefix: process.env.ATULYA_API_TENANT_SCHEMA_PREFIX || "user",
      },
      admin: {
        configured: adminConfigured,
      },
      dataplane: {
        url: DATAPLANE_URL,
      },
    },
    { status: 200 }
  );
}

export async function POST() {
  return NextResponse.json(
    {
      ok: true,
      logout_mode: "local",
    },
    { status: 200 }
  );
}
