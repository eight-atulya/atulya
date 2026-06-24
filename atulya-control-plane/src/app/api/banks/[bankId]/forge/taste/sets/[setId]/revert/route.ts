import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ bankId: string; setId: string }> }
) {
  try {
    const { bankId, setId } = await params;
    const res = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${bankId}/forge/taste/sets/${setId}/revert`,
      { method: "POST", headers: getDataplaneHeaders() }
    );
    const data = await res.json();
    if (!res.ok)
      return NextResponse.json({ error: data.detail || "Failed" }, { status: res.status });
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error("Error reverting taste set:", error);
    return NextResponse.json({ error: "Failed to revert taste set" }, { status: 500 });
  }
}
