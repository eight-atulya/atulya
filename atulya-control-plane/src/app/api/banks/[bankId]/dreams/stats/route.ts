import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeadersForRequest } from "@/lib/atulya-client";

export async function GET(request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  const { bankId } = await params;
  const res = await fetch(`${DATAPLANE_URL}/v1/default/banks/${bankId}/dreams/stats`, {
    headers: getDataplaneHeadersForRequest(request, { "Content-Type": "application/json" }),
  });
  const data = await res.json();
  if (!res.ok) return NextResponse.json({ error: data.detail || "Failed" }, { status: res.status });
  return NextResponse.json(data);
}
