import { NextRequest, NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeadersForRequest } from "@/lib/atulya-client";

export async function GET(request: NextRequest) {
  let res: Response;
  try {
    res = await fetch(`${DATAPLANE_URL}/v1/auth/me`, {
      headers: getDataplaneHeadersForRequest(request),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "Dataplane unavailable" }, { status: 503 });
  }
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
