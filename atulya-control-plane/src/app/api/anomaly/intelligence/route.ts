import { NextRequest, NextResponse } from "next/server";

import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const bankId = body?.bank_id ?? body?.agent_id;

    if (!bankId || typeof bankId !== "string") {
      return NextResponse.json({ error: "bank_id is required" }, { status: 400 });
    }

    const payload = {
      limit: typeof body.limit === "number" ? body.limit : undefined,
      status: typeof body.status === "string" ? body.status : undefined,
      anomaly_types: Array.isArray(body.anomaly_types) ? body.anomaly_types : undefined,
      min_severity: typeof body.min_severity === "number" ? body.min_severity : undefined,
    };

    const response = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${encodeURIComponent(bankId)}/anomaly/intelligence`,
      {
        method: "POST",
        headers: getDataplaneHeaders(),
        body: JSON.stringify(payload),
        cache: "no-store",
      }
    );

    const responseBody = await response.json();
    if (!response.ok) {
      return NextResponse.json(
        {
          error:
            responseBody.detail || responseBody.error || "Failed to fetch anomaly intelligence",
        },
        { status: response.status }
      );
    }

    return NextResponse.json(responseBody, { status: 200 });
  } catch (error) {
    console.error("Error fetching anomaly intelligence:", error);
    return NextResponse.json({ error: "Failed to fetch anomaly intelligence" }, { status: 500 });
  }
}
