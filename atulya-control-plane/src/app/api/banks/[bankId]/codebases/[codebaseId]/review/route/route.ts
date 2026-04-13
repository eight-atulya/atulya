import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

function parseJsonOrText(text: string): unknown {
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { error: text };
  }
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ bankId: string; codebaseId: string }> }
) {
  try {
    const { bankId, codebaseId } = await params;
    const body = await request.json();
    const response = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${bankId}/codebases/${codebaseId}/review/route`,
      {
        method: "POST",
        headers: getDataplaneHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(body),
      }
    );

    const text = await response.text();
    return NextResponse.json(parseJsonOrText(text), { status: response.status });
  } catch (error) {
    console.error("Error routing codebase review items:", error);
    return NextResponse.json({ error: "Failed to route codebase review items" }, { status: 500 });
  }
}
