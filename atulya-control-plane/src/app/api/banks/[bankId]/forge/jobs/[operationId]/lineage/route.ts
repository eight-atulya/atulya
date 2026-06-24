import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ bankId: string; operationId: string }> }
) {
  try {
    const { bankId, operationId } = await params;
    const res = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${bankId}/forge/jobs/${operationId}/lineage`,
      { headers: getDataplaneHeaders() }
    );
    const data = await res.json();
    if (!res.ok)
      return NextResponse.json({ error: data.detail || "Failed" }, { status: res.status });
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error("Error fetching forge lineage:", error);
    return NextResponse.json({ error: "Failed to fetch forge lineage" }, { status: 500 });
  }
}
