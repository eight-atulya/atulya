import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ bankId: string; datasetId: string }> }
) {
  try {
    const { bankId, datasetId } = await params;
    const res = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${bankId}/forge/taste/datasets/${datasetId}`,
      { headers: getDataplaneHeaders() }
    );
    const data = await res.json();
    if (!res.ok)
      return NextResponse.json({ error: data.detail || "Failed" }, { status: res.status });
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error("Error getting taste dataset:", error);
    return NextResponse.json({ error: "Failed to get taste dataset" }, { status: 500 });
  }
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ bankId: string; datasetId: string }> }
) {
  try {
    const { bankId, datasetId } = await params;
    const body = await request.json();
    const res = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${bankId}/forge/taste/datasets/${datasetId}`,
      {
        method: "PATCH",
        headers: getDataplaneHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(body),
      }
    );
    const data = await res.json();
    if (!res.ok)
      return NextResponse.json({ error: data.detail || "Failed" }, { status: res.status });
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error("Error updating taste dataset:", error);
    return NextResponse.json({ error: "Failed to update taste dataset" }, { status: 500 });
  }
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ bankId: string; datasetId: string }> }
) {
  try {
    const { bankId, datasetId } = await params;
    const res = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${bankId}/forge/taste/datasets/${datasetId}`,
      { method: "DELETE", headers: getDataplaneHeaders() }
    );
    const data = await res.json();
    if (!res.ok)
      return NextResponse.json({ error: data.detail || "Failed" }, { status: res.status });
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error("Error deleting taste dataset:", error);
    return NextResponse.json({ error: "Failed to delete taste dataset" }, { status: 500 });
  }
}
