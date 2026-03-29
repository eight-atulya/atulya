import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ bankId: string; predictionId: string }> }
) {
  try {
    const { bankId, predictionId } = await params;
    const body = await request.json().catch(() => ({}));
    const res = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${bankId}/dreams/predictions/${predictionId}/outcome`,
      {
        method: "POST",
        headers: getDataplaneHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(body || {}),
      }
    );
    const data = await res.json();
    if (!res.ok)
      return NextResponse.json({ error: data.detail || "Failed" }, { status: res.status });
    return NextResponse.json(data);
  } catch (error) {
    console.error("Error updating dream prediction outcome:", error);
    return NextResponse.json(
      { error: "Failed to update dream prediction outcome" },
      { status: 500 }
    );
  }
}
