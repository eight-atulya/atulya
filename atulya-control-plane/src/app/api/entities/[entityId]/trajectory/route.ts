import { NextRequest, NextResponse } from "next/server";
import { sdk, lowLevelClient } from "@/lib/atulya-client";

export async function GET(
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

    const response = await sdk.getEntityTrajectory({
      client: lowLevelClient,
      path: {
        bank_id: bankId,
        entity_id: decodedEntityId,
      },
    });

    if (response.error) {
      const httpStatus =
        "response" in response && response.response instanceof Response
          ? response.response.status
          : 500;
      return NextResponse.json({ error: response.error }, { status: httpStatus });
    }

    return NextResponse.json(response.data, { status: 200 });
  } catch (error) {
    console.error("Error getting entity trajectory:", error);
    return NextResponse.json({ error: "Failed to get entity trajectory" }, { status: 500 });
  }
}
