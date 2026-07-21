import { NextRequest, NextResponse } from "next/server";
import { canUsePlatformAdmin, getCurrentIdentity, getSessionToken } from "@/lib/server-auth";

const DATAPLANE_URL = process.env.ATULYA_CP_DATAPLANE_API_URL || "http://localhost:8888";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const identity = await getCurrentIdentity();
  if (!canUsePlatformAdmin(identity)) {
    return NextResponse.json(
      {
        detail: {
          code: "permission_denied",
          missing_action: "system.admin",
          required_scope: "system:*",
        },
      },
      { status: identity ? 403 : 401 }
    );
  }
  const token = await getSessionToken();
  if (!token) {
    return NextResponse.json({ detail: { code: "session_required" } }, { status: 401 });
  }
  const { path } = await context.params;
  const suffix = path.map(encodeURIComponent).join("/");
  const method = request.method;
  const query = request.nextUrl.searchParams.toString();
  const url = `${DATAPLANE_URL}/v1/platform/${suffix}${query ? `?${query}` : ""}`;
  const res = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": request.headers.get("content-type") || "application/json",
    },
    body: method === "GET" || method === "HEAD" ? undefined : await request.text(),
    cache: "no-store",
  }).catch(() => null);
  if (!res) {
    return NextResponse.json({ detail: { code: "dataplane_unavailable" } }, { status: 503 });
  }
  const text = await res.text();
  if (res.status === 404 && text.includes("Not Found")) {
    return NextResponse.json(
      {
        detail: {
          code: "platform_routes_disabled",
          message: "Set ATULYA_API_ADMIN_ENABLED=true on the API and restart it.",
        },
      },
      { status: 503 }
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
