import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function GET(request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  try {
    const { bankId } = await params;
    if (!bankId) {
      return NextResponse.json({ error: "bank_id is required" }, { status: 400 });
    }

    const { searchParams } = new URL(request.url);
    const horizonHours = searchParams.get("horizon_hours");
    const query = horizonHours ? `?horizon_hours=${encodeURIComponent(horizonHours)}` : "";

    const response = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${bankId}/sub-routine/predictions${query}`,
      {
        method: "GET",
        headers: getDataplaneHeaders(),
      }
    );

    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json(
        { error: errorText || "Failed to get sub_routine predictions" },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error("Error getting sub_routine predictions:", error);
    return NextResponse.json({ error: "Failed to get sub_routine predictions" }, { status: 500 });
  }
}
