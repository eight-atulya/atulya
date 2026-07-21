import { NextRequest, NextResponse } from "next/server";
import { ATULYA_SESSION_COOKIE, DATAPLANE_URL } from "@/lib/atulya-client";

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ sessionId: string }> }
) {
  const token = request.cookies.get(ATULYA_SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ detail: { code: "session_required" } }, { status: 401 });
  const { sessionId } = await context.params;
  const response = await fetch(
    `${DATAPLANE_URL}/v1/auth/sessions/${encodeURIComponent(sessionId)}`,
    {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    }
  ).catch(() => null);
  if (!response) return NextResponse.json({ detail: "Dataplane unavailable" }, { status: 503 });
  const next = new NextResponse(await response.text(), {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
  if (response.ok) {
    const me = await fetch(`${DATAPLANE_URL}/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    if (!me.ok) next.cookies.delete(ATULYA_SESSION_COOKIE);
  }
  return next;
}
