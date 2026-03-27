import { NextResponse } from "next/server";

type RemoteBanksRequest = {
  remote_endpoint?: string;
  remote_api_key?: string;
};

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as RemoteBanksRequest;
    const remoteEndpoint = body.remote_endpoint?.trim();
    const remoteApiKey = body.remote_api_key?.trim() ?? "";

    if (!remoteEndpoint) {
      return NextResponse.json({ error: "remote_endpoint is required" }, { status: 400 });
    }

    let baseUrl: URL;
    try {
      baseUrl = new URL(remoteEndpoint);
    } catch {
      return NextResponse.json({ error: "remote_endpoint must be a valid URL" }, { status: 400 });
    }

    if (baseUrl.protocol !== "http:" && baseUrl.protocol !== "https:") {
      return NextResponse.json(
        { error: "Only http/https endpoints are supported" },
        { status: 400 }
      );
    }

    const banksUrl = `${baseUrl.toString().replace(/\/+$/, "")}/v1/default/banks`;
    const headers: Record<string, string> = { Accept: "application/json" };
    if (remoteApiKey) {
      headers.Authorization = `Bearer ${remoteApiKey}`;
    }

    const response = await fetch(banksUrl, {
      method: "GET",
      headers,
      cache: "no-store",
    });

    if (!response.ok) {
      const text = await response.text();
      return NextResponse.json(
        { error: text || `Remote returned ${response.status}` },
        { status: response.status }
      );
    }

    const data = await response.json();
    const banks = (data?.banks ?? data ?? []) as Array<{ bank_id: string }>;
    const normalized = Array.isArray(banks)
      ? banks
          .filter((b) => b && typeof b.bank_id === "string" && b.bank_id.trim().length > 0)
          .map((b) => ({ bank_id: b.bank_id }))
      : [];

    return NextResponse.json({ banks: normalized }, { status: 200 });
  } catch (error) {
    console.error("Error fetching remote banks:", error);
    return NextResponse.json({ error: "Failed to fetch remote banks" }, { status: 500 });
  }
}
