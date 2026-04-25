import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function GET(_request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  try {
    const { bankId } = await params;
    const response = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${encodeURIComponent(bankId)}/entity-intelligence`,
      {
        headers: getDataplaneHeaders(),
        cache: "no-store",
      }
    );
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error("Error getting entity intelligence:", error);
    return NextResponse.json({ error: "Failed to get entity intelligence" }, { status: 500 });
  }
}
