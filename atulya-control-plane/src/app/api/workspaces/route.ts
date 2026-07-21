import { NextRequest, NextResponse } from "next/server";
import { getSessionToken } from "@/lib/server-auth";

const DATAPLANE_URL = process.env.ATULYA_CP_DATAPLANE_API_URL || "http://localhost:8888";

export async function POST(request: NextRequest) {
  const token = await getSessionToken();
  if (!token) {
    return NextResponse.json({ detail: { code: "session_required" } }, { status: 401 });
  }
  const response = await fetch(`${DATAPLANE_URL}/v1/orgs`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: await request.text(),
    cache: "no-store",
  }).catch(() => null);
  if (!response) {
    return NextResponse.json({ detail: { code: "dataplane_unavailable" } }, { status: 503 });
  }
  return new NextResponse(await response.text(), {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") || "application/json" },
  });
}
