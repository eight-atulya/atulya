import { NextResponse } from "next/server";
import { sdk, lowLevelClient } from "@/lib/atulya-client";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ bankId: string; operationId: string }> }
) {
  try {
    const { bankId, operationId } = await params;

    if (!bankId) {
      return NextResponse.json({ error: "bank_id is required" }, { status: 400 });
    }

    if (!operationId) {
      return NextResponse.json({ error: "operation_id is required" }, { status: 400 });
    }

    const response = await sdk.getOperationStatus({
      client: lowLevelClient,
      path: { bank_id: bankId, operation_id: operationId },
    });

    if (response.error) {
      console.error("API error getting operation status:", response.error);
      return NextResponse.json({ error: "Failed to get operation status" }, { status: 500 });
    }

    return NextResponse.json(response.data, { status: 200 });
  } catch (error) {
    console.error("Error getting operation status:", error);
    return NextResponse.json({ error: "Failed to get operation status" }, { status: 500 });
  }
}

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ bankId: string; operationId: string }> }
) {
  try {
    const { bankId, operationId } = await params;

    if (!bankId) {
      return NextResponse.json({ error: "bank_id is required" }, { status: 400 });
    }

    if (!operationId) {
      return NextResponse.json({ error: "operation_id is required" }, { status: 400 });
    }

    const response = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${encodeURIComponent(bankId)}/operations/${encodeURIComponent(operationId)}/retry`,
      {
        method: "POST",
        headers: getDataplaneHeaders({
          "Content-Type": "application/json",
        }),
      }
    );

    const payload = await response
      .json()
      .catch(() => ({ error: "Failed to parse retry response" }));
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    console.error("Error retrying operation:", error);
    return NextResponse.json({ error: "Failed to retry operation" }, { status: 500 });
  }
}
