import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ bankId: string; proposalId: string }> }
) {
  try {
    const { bankId, proposalId } = await params;
    const body = await request.json().catch(() => ({}));
    const res = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${bankId}/dreams/proposals/${proposalId}/review`,
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
    console.error("Error reviewing dream proposal:", error);
    return NextResponse.json({ error: "Failed to review dream proposal" }, { status: 500 });
  }
}
