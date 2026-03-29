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

function serializeReflectResponse(data: any) {
  if (!data) return {};

  return {
    text: data.text ?? "",
    based_on: data.based_on
      ? {
          memories: Array.isArray(data.based_on.memories) ? data.based_on.memories : [],
          mental_models: Array.isArray(data.based_on.mental_models)
            ? data.based_on.mental_models
            : [],
          directives: Array.isArray(data.based_on.directives) ? data.based_on.directives : [],
        }
      : null,
    structured_output: data.structured_output ?? null,
    usage: data.usage
      ? {
          input_tokens: data.usage.input_tokens ?? 0,
          output_tokens: data.usage.output_tokens ?? 0,
          total_tokens: data.usage.total_tokens ?? 0,
        }
      : null,
    trace: data.trace
      ? {
          tool_calls: Array.isArray(data.trace.tool_calls) ? data.trace.tool_calls : [],
          llm_calls: Array.isArray(data.trace.llm_calls) ? data.trace.llm_calls : [],
        }
      : null,
  };
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const bankId = body.bank_id || body.agent_id || "default";
    const {
      query,
      budget,
      thinking_budget,
      include_facts,
      include_tool_calls,
      tags,
      tags_match,
      max_tokens,
    } = body;

    const requestBody: any = {
      query,
      budget: budget || (thinking_budget ? "mid" : "low"),
      tags,
      tags_match,
      max_tokens: max_tokens || undefined,
    };

    // Add include options if specified
    const includeOptions: any = {};
    if (include_facts) {
      includeOptions.facts = {};
    }
    if (include_tool_calls) {
      includeOptions.tool_calls = {};
    }
    if (Object.keys(includeOptions).length > 0) {
      requestBody.include = includeOptions;
    }

    const response = await sdk.reflect({
      client: lowLevelClient,
      path: { bank_id: bankId },
      body: requestBody,
    });

    if (response.error) {
      const status = response.response?.status ?? 500;
      return NextResponse.json({ error: extractSdkErrorMessage(response.error) }, { status });
    }

    return NextResponse.json(serializeReflectResponse(response.data), { status: 200 });
  } catch (error) {
    console.error("Error reflecting:", error);
    return NextResponse.json({ error: "Failed to reflect" }, { status: 500 });
  }
}
