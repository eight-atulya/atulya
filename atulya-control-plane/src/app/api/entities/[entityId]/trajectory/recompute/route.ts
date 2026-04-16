import { NextRequest, NextResponse } from "next/server";
import { sdk, lowLevelClient } from "@/lib/atulya-client";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ entityId: string }> }
) {
  try {
    const { entityId } = await params;
    const searchParams = request.nextUrl.searchParams;
    const bankId = searchParams.get("bank_id");

    if (!bankId) {
      return NextResponse.json({ error: "bank_id is required" }, { status: 400 });
    }

    const decodedEntityId = decodeURIComponent(entityId);

    const response = await sdk.postEntityTrajectoryRecompute({
      client: lowLevelClient,
      path: {
        bank_id: bankId,
        entity_id: decodedEntityId,
      },
    });

    if (response.error) {
      const status = (response.error as { status?: number }).status ?? 500;
      return NextResponse.json({ error: response.error }, { status });
    }

    return NextResponse.json(response.data, { status: 200 });
  } catch (error) {
    console.error("Error queueing entity trajectory recompute:", error);
    return NextResponse.json({ error: "Failed to queue recompute" }, { status: 500 });
  }
}
