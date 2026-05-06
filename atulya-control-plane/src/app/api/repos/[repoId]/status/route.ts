import { NextResponse } from "next/server";
import { fetchDataplaneJson } from "@/lib/dataplane-proxy";
import { dataplaneErrorResponse } from "@/lib/dataplane-route";

export async function GET(request: Request, { params }: { params: Promise<{ repoId: string }> }) {
  const { repoId } = await params;
  const url = new URL(request.url);
  const query = url.searchParams.toString();
  const response = await fetchDataplaneJson({
    path: `/v1/default/repos/${encodeURIComponent(repoId)}/status${query ? `?${query}` : ""}`,
    method: "GET",
  });
  if (!response.ok) {
    return dataplaneErrorResponse(response.status, response.data, "Failed to load repo status");
  }
  return NextResponse.json(response.data, { status: response.status });
}
