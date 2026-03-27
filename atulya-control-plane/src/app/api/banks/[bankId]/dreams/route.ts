import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function GET(request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  const { bankId } = await params;
  const url = new URL(request.url);
  const limit = url.searchParams.get("limit") || "20";
  const res = await fetch(`${DATAPLANE_URL}/v1/default/banks/${bankId}/dreams?limit=${limit}`, {
    headers: getDataplaneHeaders({ "Content-Type": "application/json" }),
  });
  const data = await res.json();
  if (!res.ok) return NextResponse.json({ error: data.detail || "Failed" }, { status: res.status });
  return NextResponse.json(data);
}
