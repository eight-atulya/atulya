import { NextRequest, NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function GET(request: NextRequest) {
  try {
    const searchParams = request.nextUrl.searchParams;
    const bankId = searchParams.get("bank_id") || searchParams.get("agent_id");

    if (!bankId) {
      return NextResponse.json({ error: "bank_id is required" }, { status: 400 });
    }

    const params = new URLSearchParams();
    const passthroughKeys = ["type", "limit", "q", "tags_match"];
    for (const key of passthroughKeys) {
      const value = searchParams.get(key);
      if (value) params.set(key, value);
    }
    for (const tag of searchParams.getAll("tags")) {
      params.append("tags", tag);
    }

    const response = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${encodeURIComponent(bankId)}/timeline?${params.toString()}`,
      {
        headers: getDataplaneHeaders(),
        cache: "no-store",
      }
    );

    const payload = await response.json();
    if (!response.ok) {
      return NextResponse.json(
        { error: payload.detail || payload.error || "Failed to fetch timeline" },
        { status: response.status }
      );
    }

    return NextResponse.json(payload, { status: 200 });
  } catch (error) {
    console.error("Error fetching timeline:", error);
    return NextResponse.json({ error: "Failed to fetch timeline" }, { status: 500 });
  }
}
