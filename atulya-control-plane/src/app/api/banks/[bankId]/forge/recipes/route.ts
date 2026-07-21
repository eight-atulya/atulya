import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeadersForRequest } from "@/lib/atulya-client";

export async function GET(request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  try {
    const { bankId } = await params;
    const { searchParams } = new URL(request.url);
    const tags = searchParams.getAll("domain_tags");
    const query = tags.length
      ? `?${tags.map((t) => `domain_tags=${encodeURIComponent(t)}`).join("&")}`
      : "";
    const res = await fetch(`${DATAPLANE_URL}/v1/default/banks/${bankId}/forge/recipes${query}`, {
      headers: getDataplaneHeadersForRequest(request),
    });
    const data = await res.json();
    if (!res.ok)
      return NextResponse.json({ error: data.detail || "Failed" }, { status: res.status });
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error("Error listing forge recipes:", error);
    return NextResponse.json({ error: "Failed to list forge recipes" }, { status: 500 });
  }
}
