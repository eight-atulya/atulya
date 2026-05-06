import { NextResponse } from "next/server";
import { fetchDataplaneJson } from "@/lib/dataplane-proxy";
import { dataplaneErrorResponse } from "@/lib/dataplane-route";

export async function GET(_request: Request, { params }: { params: Promise<{ repoId: string }> }) {
  const { repoId } = await params;
  const response = await fetchDataplaneJson({
    path: `/v1/default/repos/${encodeURIComponent(repoId)}/branches`,
    method: "GET",
  });
  if (!response.ok) {
    return dataplaneErrorResponse(response.status, response.data, "Failed to load repo branches");
  }
  return NextResponse.json(response.data, { status: response.status });
}

export async function POST(request: Request, { params }: { params: Promise<{ repoId: string }> }) {
  const { repoId } = await params;
  const body = await request.json();
  const response = await fetchDataplaneJson({
    path: `/v1/default/repos/${encodeURIComponent(repoId)}/branches`,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    return dataplaneErrorResponse(response.status, response.data, "Failed to create repo branch");
  }
  return NextResponse.json(response.data, { status: response.status });
}
