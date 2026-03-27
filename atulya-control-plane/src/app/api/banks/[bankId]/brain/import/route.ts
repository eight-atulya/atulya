import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function POST(request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  try {
    const { bankId } = await params;
    if (!bankId) {
      return NextResponse.json({ error: "bank_id is required" }, { status: 400 });
    }

    const formData = await request.formData();
    const response = await fetch(`${DATAPLANE_URL}/v1/default/banks/${bankId}/brain/import`, {
      method: "POST",
      headers: getDataplaneHeaders(),
      body: formData,
    });

    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json(
        { error: errorText || "Failed to import brain snapshot" },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error("Error importing brain snapshot:", error);
    return NextResponse.json({ error: "Failed to import brain snapshot" }, { status: 500 });
  }
}
