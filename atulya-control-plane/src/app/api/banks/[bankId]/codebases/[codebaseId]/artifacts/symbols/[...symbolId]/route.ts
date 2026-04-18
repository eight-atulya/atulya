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
  {
    params,
  }: {
    params: Promise<{ bankId: string; codebaseId: string; symbolId: string[] }>;
  }
) {
  try {
    const { bankId, codebaseId, symbolId } = await params;
    const segments = Array.isArray(symbolId) ? symbolId : [symbolId];
    const safeSymbolId = segments.map((segment) => encodeURIComponent(segment)).join("/");
    const response = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${bankId}/codebases/${codebaseId}/artifacts/symbols/${safeSymbolId}${request.nextUrl.search}`,
      {
        method: "GET",
        headers: getDataplaneHeaders(),
        cache: "no-store",
      }
    );

    const text = await response.text();
    return NextResponse.json(parseJsonOrText(text), { status: response.status });
  } catch (error) {
    console.error("Error fetching codebase symbol card:", error);
    return NextResponse.json({ error: "Failed to fetch codebase symbol card" }, { status: 500 });
  }
}
