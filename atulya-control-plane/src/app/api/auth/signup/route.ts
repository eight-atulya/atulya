import { NextRequest, NextResponse } from "next/server";
import { ATULYA_SESSION_COOKIE, DATAPLANE_URL } from "@/lib/atulya-client";

const ATULYA_LOGGED_OUT_COOKIE = "atulya_logged_out";

export async function POST(request: NextRequest) {
  const body = await request.json();
  let res: Response;
  try {
    res = await fetch(`${DATAPLANE_URL}/v1/auth/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "Dataplane unavailable" }, { status: 503 });
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json(data, { status: res.status });
  }

  const response = NextResponse.json(data, { status: res.status });
  if (data.token) {
    response.cookies.set(ATULYA_SESSION_COOKIE, data.token, {
      httpOnly: true,
      sameSite: "lax",
      secure:
        process.env.ATULYA_CP_COOKIE_SECURE === "true" || process.env.NODE_ENV === "production",
      path: "/",
      expires: data.expires_at ? new Date(data.expires_at) : undefined,
    });
  }
  response.cookies.delete(ATULYA_LOGGED_OUT_COOKIE);
  return response;
}
