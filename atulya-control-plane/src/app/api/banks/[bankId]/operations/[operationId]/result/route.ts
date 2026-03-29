import { NextResponse } from "next/server";
import { sdk, lowLevelClient } from "@/lib/atulya-client";

function extractSdkErrorMessage(error: unknown): string {
  if (!error || typeof error !== "object") return "Request failed";
  const detail =
    (error as { detail?: unknown }).detail ??
    (error as { message?: unknown }).message ??
    (error as { error?: unknown }).error;
  return typeof detail === "string" ? detail : "Request failed";
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ bankId: string; operationId: string }> }
) {
  try {
    const { bankId, operationId } = await params;

    if (!bankId) {
      return NextResponse.json({ error: "bank_id is required" }, { status: 400 });
    }

    if (!operationId) {
      return NextResponse.json({ error: "operation_id is required" }, { status: 400 });
    }

    const response = await sdk.getOperationResult({
      client: lowLevelClient,
      path: { bank_id: bankId, operation_id: operationId },
    });

    if (response.error) {
      const status = response.response?.status ?? 500;
      console.error("API error getting operation result:", response.error);
      return NextResponse.json({ error: extractSdkErrorMessage(response.error) }, { status });
    }

    return NextResponse.json(response.data || {}, { status: 200 });
  } catch (error) {
    console.error("Error getting operation result:", error);
    return NextResponse.json({ error: "Failed to get operation result" }, { status: 500 });
  }
}
