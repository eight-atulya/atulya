import { NextResponse } from "next/server";
import { fetchDataplaneJson } from "@/lib/dataplane-proxy";
import { dataplaneErrorResponse } from "@/lib/dataplane-route";

export async function GET(request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  const { bankId } = await params;
  const repoLookup = await fetchDataplaneJson({
    request,
    path: `/v1/default/banks/${encodeURIComponent(bankId)}/repo`,
    method: "GET",
  });

  if (!repoLookup.ok) {
    return dataplaneErrorResponse(repoLookup.status, repoLookup.data, "Failed to load memory repo");
  }

  return NextResponse.json(repoLookup.data, { status: repoLookup.status });
}
