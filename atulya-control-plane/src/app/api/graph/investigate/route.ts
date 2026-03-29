import { NextRequest, NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const bankId = body.bank_id || body.agent_id;

    if (!bankId) {
      return NextResponse.json({ error: "bank_id is required" }, { status: 400 });
    }

    const response = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${encodeURIComponent(bankId)}/graph/investigate`,
      {
        method: "POST",
        headers: getDataplaneHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          query: body.query,
          type: body.type,
          tags: body.tags,
          tags_match: body.tags_match,
          confidence_min: body.confidence_min,
          node_kind: body.node_kind,
          window_days: body.window_days,
          limit: body.limit,
        }),
      }
    );

    const payload = await response.json();
    if (!response.ok) {
      return NextResponse.json(
        { error: payload.detail || payload.error || "Failed to investigate graph intelligence" },
        { status: response.status }
      );
    }

    return NextResponse.json(payload, { status: 200 });
  } catch (error) {
    console.error("Error investigating graph intelligence:", error);
    return NextResponse.json(
      { error: "Failed to investigate graph intelligence" },
      { status: 500 }
    );
  }
}
