import { NextRequest, NextResponse } from "next/server";
import {
  ATULYA_SESSION_COOKIE,
  DATAPLANE_URL,
  getDataplaneHeadersForRequest,
} from "@/lib/atulya-client";

const ATULYA_LOGGED_OUT_COOKIE = "atulya_logged_out";

export async function POST(request: NextRequest) {
  await fetch(`${DATAPLANE_URL}/v1/auth/logout`, {
    method: "POST",
    headers: getDataplaneHeadersForRequest(request),
    cache: "no-store",
  }).catch(() => null);

  const response = NextResponse.json({ ok: true });
  response.cookies.delete(ATULYA_SESSION_COOKIE);
  response.cookies.set(ATULYA_LOGGED_OUT_COOKIE, "1", {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.ATULYA_CP_COOKIE_SECURE === "true" || process.env.NODE_ENV === "production",
    path: "/",
  });
  return response;
}
