import { NextRequest, NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

function extractErrorMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "detail" in detail) {
    const d = (detail as { detail: unknown }).detail;
    if (typeof d === "string") return d;
  }
  return "Internet research failed";
}

/**
 * Proxy to atulya-api internet research agent (uses bank LLM + optional web stack on API host).
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const bankId = body.bank_id || body.agent_id || "default";
    const { query, budget, max_tokens, include } = body;

    if (!query || typeof query !== "string" || !query.trim()) {
      return NextResponse.json({ error: "query is required" }, { status: 400 });
    }

    const payload: Record<string, unknown> = {
      query: query.trim(),
      budget: budget || "mid",
      max_tokens: max_tokens || 4096,
    };
    if (include && typeof include === "object") {
      payload.include = include;
    }

    const res = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${encodeURIComponent(bankId)}/internet/research`,
      {
        method: "POST",
        headers: getDataplaneHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(payload),
      }
    );

    const text = await res.text();
    let data: unknown;
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }

    if (!res.ok) {
      const msg = extractErrorMessage(
        data && typeof data === "object" && "detail" in data
          ? (data as { detail: unknown }).detail
          : data
      );
      return NextResponse.json({ error: msg }, { status: res.status });
    }

    return NextResponse.json(data, { status: 200 });
  } catch (e) {
    console.error("[internet/research]", e);
    return NextResponse.json({ error: "Request failed" }, { status: 500 });
  }
}
