import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeadersForRequest } from "@/lib/atulya-client";

export async function POST(request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  try {
    const { bankId } = await params;
    const body = await request.json();
    const res = await fetch(`${DATAPLANE_URL}/v1/default/banks/${bankId}/forge/export`, {
      method: "POST",
      headers: getDataplaneHeadersForRequest(request, { "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok)
      return NextResponse.json({ error: data.detail || "Failed" }, { status: res.status });
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error("Error exporting forge job:", error);
    return NextResponse.json({ error: "Failed to export forge job" }, { status: 500 });
  }
}
