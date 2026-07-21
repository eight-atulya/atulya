import { NextResponse } from "next/server";
import { fetchDataplaneJson } from "@/lib/dataplane-proxy";
import { dataplaneErrorResponse } from "@/lib/dataplane-route";

export async function GET(request: Request, { params }: { params: Promise<{ repoId: string }> }) {
  const { repoId } = await params;
  const url = new URL(request.url);
  const query = url.searchParams.toString();
  const response = await fetchDataplaneJson({
    request,
    path: `/v1/default/repos/${encodeURIComponent(repoId)}/log${query ? `?${query}` : ""}`,
    method: "GET",
  });
  if (!response.ok) {
    return dataplaneErrorResponse(response.status, response.data, "Failed to load repo history");
  }
  return NextResponse.json(response.data, { status: response.status });
}
