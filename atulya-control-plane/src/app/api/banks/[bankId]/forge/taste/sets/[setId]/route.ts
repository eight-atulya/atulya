import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeadersForRequest } from "@/lib/atulya-client";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ bankId: string; setId: string }> }
) {
  try {
    const { bankId, setId } = await params;
    const res = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${bankId}/forge/taste/sets/${setId}`,
      { headers: getDataplaneHeadersForRequest(request) }
    );
    const data = await res.json();
    if (!res.ok)
      return NextResponse.json({ error: data.detail || "Failed" }, { status: res.status });
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error("Error getting taste set:", error);
    return NextResponse.json({ error: "Failed to get taste set" }, { status: 500 });
  }
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ bankId: string; setId: string }> }
) {
  try {
    const { bankId, setId } = await params;
    const body = await request.json();
    const res = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${bankId}/forge/taste/sets/${setId}`,
      {
        method: "PATCH",
        headers: getDataplaneHeadersForRequest(request, { "Content-Type": "application/json" }),
        body: JSON.stringify(body),
      }
    );
    const data = await res.json();
    if (!res.ok)
      return NextResponse.json({ error: data.detail || "Failed" }, { status: res.status });
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error("Error updating taste set:", error);
    return NextResponse.json({ error: "Failed to update taste set" }, { status: 500 });
  }
}
