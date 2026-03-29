import { NextRequest, NextResponse } from "next/server";
import { sdk, lowLevelClient } from "@/lib/atulya-client";

function extractSdkErrorMessage(error: unknown): string {
  if (!error || typeof error !== "object") return "Request failed";
  const detail =
    (error as { detail?: unknown }).detail ??
    (error as { message?: unknown }).message ??
    (error as { error?: unknown }).error;
  return typeof detail === "string" ? detail : "Request failed";
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const bankId = body.bank_id || body.agent_id || "default";
    const response = await sdk.submitAsyncReflect({
      client: lowLevelClient,
      path: { bank_id: bankId },
      body: {
        query: body.query,
        budget: body.budget,
        context: body.context,
        max_tokens: body.max_tokens,
        include: {
          ...(body.include_facts ? { facts: {} } : {}),
          ...(body.include_tool_calls ? { tool_calls: {} } : {}),
        },
        response_schema: body.response_schema,
        tags: body.tags,
        tags_match: body.tags_match,
      },
    });

    if (response.error) {
      const status = response.response?.status ?? 500;
      return NextResponse.json({ error: extractSdkErrorMessage(response.error) }, { status });
    }

    return NextResponse.json(response.data || {}, { status: 200 });
  } catch (error) {
    console.error("Error submitting async reflect:", error);
    return NextResponse.json({ error: "Failed to submit reflect" }, { status: 500 });
  }
}
