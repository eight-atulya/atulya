import { NextResponse } from "next/server";
import { DATAPLANE_URL } from "@/lib/atulya-client";

export async function GET() {
  try {
    const res = await fetch(`${DATAPLANE_URL}/v1/auth/signup-state`, {
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json(
      { mode: "disabled", available: false, org_count: 0, detail: "Dataplane unavailable" },
      { status: 503 }
    );
  }
}
