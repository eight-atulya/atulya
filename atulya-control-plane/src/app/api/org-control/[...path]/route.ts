import { NextRequest, NextResponse } from "next/server";
import { getSessionToken } from "@/lib/server-auth";

const DATAPLANE_URL = process.env.ATULYA_CP_DATAPLANE_API_URL || "http://localhost:8888";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: { code: "session_required" } }, { status: 401 });

  const { path } = await context.params;
  const suffix = path.map(encodeURIComponent).join("/");
  const query = request.nextUrl.searchParams.toString();
  const method = request.method;
  const response = await fetch(`${DATAPLANE_URL}/v1/orgs/${suffix}${query ? `?${query}` : ""}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": request.headers.get("content-type") || "application/json",
    },
    body: method === "GET" || method === "HEAD" ? undefined : await request.text(),
    cache: "no-store",
  }).catch(() => null);

  if (!response) return NextResponse.json({ detail: "Dataplane unavailable" }, { status: 503 });
  return new NextResponse(await response.text(), {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") || "application/json" },
  });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
