import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function POST(request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  try {
    const { bankId } = await params;
    if (!bankId) {
      return NextResponse.json({ error: "bank_id is required" }, { status: 400 });
    }

    const body = await request.json();
    const response = await fetch(`${DATAPLANE_URL}/v1/default/banks/${bankId}/brain/learn`, {
      method: "POST",
      headers: { ...getDataplaneHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errorText = await response.text();
      if (response.status === 404) {
        return NextResponse.json(
          {
            error:
              "Dataplane endpoint /v1/default/banks/{bank_id}/brain/learn is not available. " +
              "Restart/update atulya-api to a build that includes brain-to-brain learning routes.",
            details: errorText || "Not Found",
          },
          { status: 404 }
        );
      }
      return NextResponse.json(
        { error: errorText || "Failed to trigger brain learning" },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error("Error triggering brain learning:", error);
    return NextResponse.json({ error: "Failed to trigger brain learning" }, { status: 500 });
  }
}
