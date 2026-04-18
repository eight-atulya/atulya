import { NextRequest, NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

function parseJsonOrText(text: string): unknown {
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { error: text };
  }
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ bankId: string; codebaseId: string }> }
) {
  try {
    const { bankId, codebaseId } = await params;
    const response = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${bankId}/codebases/${codebaseId}/artifacts/modules${request.nextUrl.search}`,
      {
        method: "GET",
        headers: getDataplaneHeaders(),
        cache: "no-store",
      }
    );

    const text = await response.text();
    return NextResponse.json(parseJsonOrText(text), { status: response.status });
  } catch (error) {
    console.error("Error fetching codebase module briefs:", error);
    return NextResponse.json({ error: "Failed to fetch codebase module briefs" }, { status: 500 });
  }
}
