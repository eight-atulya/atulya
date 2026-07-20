import { NextRequest, NextResponse } from "next/server";
import { canUseAdminConsole, getCurrentIdentity } from "@/lib/server-auth";

const DATAPLANE_URL = process.env.ATULYA_CP_DATAPLANE_API_URL || "http://localhost:8888";
const ADMIN_KEY = process.env.ATULYA_CP_ADMIN_API_KEY || "";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!ADMIN_KEY) {
    return NextResponse.json({ detail: "Admin access not configured" }, { status: 404 });
  }
  const identity = await getCurrentIdentity();
  if (!canUseAdminConsole(identity)) {
    return NextResponse.json(
      {
        detail: "Access denied",
        missing_action: "admin.* or system.admin",
        identity,
      },
      { status: identity ? 403 : 401 }
    );
  }
  const { path } = await context.params;
  const suffix = path.map(encodeURIComponent).join("/");
  const method = request.method;
  const search = new URLSearchParams(request.nextUrl.searchParams);
  let body = method === "GET" || method === "HEAD" ? undefined : await request.text();

  if (identity && !identity.is_superuser) {
    const resource = path[0];
    if (method === "POST" && resource === "orgs") {
      return NextResponse.json(
        { detail: "Only platform superusers can create organizations" },
        { status: 403 }
      );
    }
    if (["principals", "access-grants", "audit-events"].includes(resource)) {
      const orgId = search.get("org_id");
      if (orgId && orgId !== identity.org_id) {
        return NextResponse.json(
          { detail: "Access denied for this organization" },
          { status: 403 }
        );
      }
      if (!orgId && identity.org_id) search.set("org_id", identity.org_id);
    }
    if (resource === "api-keys") {
      search.set("schema", identity.schema_name);
    }
    if (body && request.headers.get("content-type")?.includes("application/json")) {
      const data = JSON.parse(body) as Record<string, unknown>;
      if (typeof data.org_id === "string" && data.org_id !== identity.org_id) {
        return NextResponse.json(
          { detail: "Access denied for this organization" },
          { status: 403 }
        );
      }
      if (resource === "api-keys") data.schema_name = identity.schema_name;
      body = JSON.stringify(data);
    }
  }

  const query = search.toString();
  const url = `${DATAPLANE_URL}/v1/admin/${suffix}${query ? `?${query}` : ""}`;
  const res = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${ADMIN_KEY}`,
      "Content-Type": request.headers.get("content-type") || "application/json",
    },
    body,
    cache: "no-store",
  });
  const text = await res.text();
  if (res.status === 404 && text.includes("Not Found")) {
    return NextResponse.json(
      {
        detail:
          "Dataplane admin routes are not mounted. Set ATULYA_API_ADMIN_ENABLED=true and ATULYA_API_SUPERUSER_KEY on the API, then restart the API process.",
      },
      { status: 503 }
    );
  }
  if (identity && !identity.is_superuser && method === "GET" && path[0] === "orgs" && res.ok) {
    const rows = JSON.parse(text) as Array<{ id: string }>;
    return NextResponse.json(
      rows.filter((row) => row.id === identity.org_id),
      { status: res.status }
    );
  }
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("content-type") || "application/json" },
  });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
