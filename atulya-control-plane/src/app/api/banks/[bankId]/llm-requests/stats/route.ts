import { NextResponse } from "next/server";
import { dataplaneErrorResponse } from "@/lib/dataplane-route";
import { fetchDataplaneJson } from "@/lib/dataplane-proxy";

export async function GET(request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  try {
    const { bankId } = await params;
    if (!bankId) {
      return NextResponse.json({ error: "bank_id is required" }, { status: 400 });
    }

    const { searchParams } = new URL(request.url);
    const query = new URLSearchParams();
    for (const key of ["period_hours", "trunc"]) {
      const value = searchParams.get(key);
      if (value) query.set(key, value);
    }

    const suffix = query.toString() ? `?${query.toString()}` : "";
    const result = await fetchDataplaneJson({
      path: `/v1/default/banks/${encodeURIComponent(bankId)}/llm-requests/stats${suffix}`,
    });

    if (!result.ok) {
      return dataplaneErrorResponse(result.status, result.data, "Failed to load LLM trace stats");
    }
    return NextResponse.json(result.data, { status: result.status });
  } catch (error) {
    console.error("Error loading LLM trace stats:", error);
    return NextResponse.json({ error: "Failed to load LLM trace stats" }, { status: 500 });
  }
}
