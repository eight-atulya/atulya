import { NextRequest, NextResponse } from "next/server";
import { DATAPLANE_URL } from "@/lib/atulya-client";

export async function publicAuthProxy(request: NextRequest, path: string) {
  const response = await fetch(`${DATAPLANE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
    cache: "no-store",
  }).catch(() => null);
  if (!response) return NextResponse.json({ detail: "Dataplane unavailable" }, { status: 503 });
  return new NextResponse(await response.text(), {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") || "application/json" },
  });
}
