import { NextRequest, NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

function msg(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "detail" in detail) {
    const d = (detail as { detail: unknown }).detail;
    if (typeof d === "string") return d;
  }
  return "Draft enrichment failed";
}

/**
 * Optional tiny LLM pass to enrich retain draft fields.
 * Caller must still run confidence checks before applying.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const bankId = body.bank_id || body.agent_id || "default";
    const draft = body.draft;
    if (!draft || typeof draft !== "object") {
      return NextResponse.json({ error: "draft is required" }, { status: 400 });
    }
    const content = String((draft as { content?: unknown }).content || "").trim();
    if (!content) {
      return NextResponse.json({ error: "draft.content is required" }, { status: 400 });
    }

    const response_schema = {
      type: "object",
      properties: {
        confidence: { type: "number", description: "0 to 1 confidence for this enrichment" },
        context: { type: "string", description: "Short retain context line" },
        tags: { type: "array", items: { type: "string" }, description: "8-12 concise tags max" },
        entities: { type: "array", items: { type: "string" }, description: "Key entities as plain strings" },
        metadata: {
          type: "object",
          description: "Small metadata map with string values only",
        },
        observation_scopes: {
          type: "string",
          description: "Either combined or per_tag",
        },
      },
      required: ["confidence", "context", "tags"],
    };

    const enrichQuery = [
      "Enrich this retain draft conservatively.",
      "Rules: keep concise, avoid hallucinations, do not invent facts, and prefer stable tags.",
      "Return only fields requested by schema; confidence must reflect reliability.",
      "",
      "DRAFT JSON:",
      JSON.stringify(draft),
      "",
      "PRIMARY CONTENT (truncated):",
      content.slice(0, 5000),
    ].join("\n");

    const res = await fetch(`${DATAPLANE_URL}/v1/default/banks/${encodeURIComponent(bankId)}/reflect`, {
      method: "POST",
      headers: getDataplaneHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        query: enrichQuery,
        budget: "low",
        max_tokens: 300,
        include: {},
        response_schema,
      }),
    });

    const text = await res.text();
    let data: unknown;
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
    if (!res.ok) {
      return NextResponse.json({ error: msg(data) }, { status: res.status });
    }

    const structured =
      data && typeof data === "object" && "structured_output" in data
        ? (data as { structured_output?: unknown }).structured_output
        : null;
    if (!structured || typeof structured !== "object") {
      return NextResponse.json({ error: "No structured enrichment returned" }, { status: 502 });
    }

    return NextResponse.json({ enrichment: structured }, { status: 200 });
  } catch (e) {
    console.error("[internet/enrich-draft]", e);
    return NextResponse.json({ error: "Request failed" }, { status: 500 });
  }
}

