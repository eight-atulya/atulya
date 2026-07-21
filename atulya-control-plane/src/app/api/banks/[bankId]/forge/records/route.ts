import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeadersForRequest } from "@/lib/atulya-client";

export async function GET(request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  try {
    const { bankId } = await params;
    const { searchParams } = new URL(request.url);
    const query = new URLSearchParams();
    const operationId = searchParams.get("operation_id");
    const limit = searchParams.get("limit") || "50";
    const offset = searchParams.get("offset") || "0";
    if (operationId) query.set("operation_id", operationId);
    query.set("limit", limit);
    query.set("offset", offset);
    const res = await fetch(`${DATAPLANE_URL}/v1/default/banks/${bankId}/forge/records?${query}`, {
      headers: getDataplaneHeadersForRequest(request),
    });
    const data = await res.json();
    if (!res.ok)
      return NextResponse.json({ error: data.detail || "Failed" }, { status: res.status });
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error("Error listing forge records:", error);
    return NextResponse.json({ error: "Failed to list forge records" }, { status: 500 });
  }
}
