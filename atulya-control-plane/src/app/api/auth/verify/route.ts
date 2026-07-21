import { NextRequest, NextResponse } from "next/server";
import { ATULYA_SESSION_COOKIE, DATAPLANE_URL } from "@/lib/atulya-client";

export async function POST(request: NextRequest) {
  const response = await fetch(`${DATAPLANE_URL}/v1/auth/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
    cache: "no-store",
  }).catch(() => null);
  if (!response) return NextResponse.json({ detail: "Dataplane unavailable" }, { status: 503 });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) return NextResponse.json(data, { status: response.status });
  const next = NextResponse.json(data);
  next.cookies.set(ATULYA_SESSION_COOKIE, data.token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.ATULYA_CP_COOKIE_SECURE === "true" || process.env.NODE_ENV === "production",
    path: "/",
    expires: data.expires_at ? new Date(data.expires_at) : undefined,
  });
  return next;
}
