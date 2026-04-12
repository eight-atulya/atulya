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
    if (!bankId || !codebaseId) {
      return NextResponse.json({ error: "bank_id and codebase_id are required" }, { status: 400 });
    }

    const response = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${bankId}/codebases/${codebaseId}/symbols${request.nextUrl.search}`,
      {
        method: "GET",
        headers: getDataplaneHeaders(),
        cache: "no-store",
      }
    );

    const text = await response.text();
    const payload = parseJsonOrText(text);
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    console.error("Error searching codebase symbols:", error);
    return NextResponse.json({ error: "Failed to search codebase symbols" }, { status: 500 });
  }
}
