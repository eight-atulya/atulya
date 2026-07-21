import { NextResponse } from "next/server";
import { fetchDataplaneJson } from "@/lib/dataplane-proxy";
import { dataplaneErrorResponse } from "@/lib/dataplane-route";

export async function POST(request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  const { bankId } = await params;
  const body = await request.json().catch(() => ({}));
  const response = await fetchDataplaneJson({
    request,
    path: `/v1/default/banks/${encodeURIComponent(bankId)}/repos/enable`,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    return dataplaneErrorResponse(
      response.status,
      response.data,
      "Failed to enable memory repo versioning"
    );
  }

  return NextResponse.json(response.data, { status: response.status });
}
