import { NextResponse } from "next/server";
import { fetchDataplaneJson } from "@/lib/dataplane-proxy";
import { dataplaneErrorResponse } from "@/lib/dataplane-route";

export async function GET(request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  const { bankId } = await params;
  const response = await fetchDataplaneJson({
    request,
    path: `/v1/default/banks/${encodeURIComponent(bankId)}/repo/branches`,
    method: "GET",
  });
  if (!response.ok) {
    return dataplaneErrorResponse(
      response.status,
      response.data,
      "Failed to load memory repo branches for bank"
    );
  }
  return NextResponse.json(response.data, { status: response.status });
}
