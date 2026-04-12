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

export async function POST(request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  try {
    const { bankId } = await params;
    if (!bankId) {
      return NextResponse.json({ error: "bank_id is required" }, { status: 400 });
    }

    const formData = await request.formData();
    const response = await fetch(
      `${DATAPLANE_URL}/v1/default/banks/${bankId}/codebases/import/zip`,
      {
        method: "POST",
        headers: getDataplaneHeaders(),
        body: formData,
      }
    );

    const text = await response.text();
    const payload = parseJsonOrText(text);
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    console.error("Error importing ZIP codebase:", error);
    return NextResponse.json({ error: "Failed to import ZIP codebase" }, { status: 500 });
  }
}
