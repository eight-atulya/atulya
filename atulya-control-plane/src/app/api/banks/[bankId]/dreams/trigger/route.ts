import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function POST(request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  try {
    const { bankId } = await params;
    const body = await request.json().catch(() => ({}));
    const res = await fetch(`${DATAPLANE_URL}/v1/default/banks/${bankId}/dreams/trigger`, {
      method: "POST",
      headers: getDataplaneHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body || {}),
    });
    const data = await res.json();
    if (!res.ok)
      return NextResponse.json({ error: data.detail || "Failed" }, { status: res.status });
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error("Error triggering dream generation:", error);
    return NextResponse.json({ error: "Failed to trigger dream generation" }, { status: 500 });
  }
}
