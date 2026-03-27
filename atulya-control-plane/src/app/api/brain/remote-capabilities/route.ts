import { NextResponse } from "next/server";

type RemoteCapabilitiesRequest = {
  remote_endpoint?: string;
  remote_bank_id?: string;
  remote_api_key?: string;
};

type CapabilityKey =
  | "version_ok"
  | "banks_ok"
  | "brain_export_ok"
  | "mental_models_ok"
  | "memories_ok"
  | "entities_ok";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as RemoteCapabilitiesRequest;
    const remoteEndpoint = body.remote_endpoint?.trim();
    const remoteBankId = body.remote_bank_id?.trim();
    const remoteApiKey = body.remote_api_key?.trim() ?? "";

    if (!remoteEndpoint || !remoteBankId) {
      return NextResponse.json(
        { error: "remote_endpoint and remote_bank_id are required" },
        { status: 400 }
      );
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

    const base = baseUrl.toString().replace(/\/+$/, "");
    const headers: Record<string, string> = { Accept: "application/json" };
    if (remoteApiKey) {
      headers.Authorization = `Bearer ${remoteApiKey}`;
    }

    const checks: Record<CapabilityKey, string> = {
      version_ok: `${base}/v1/version`,
      banks_ok: `${base}/v1/default/banks?limit=1`,
      brain_export_ok: `${base}/v1/default/banks/${remoteBankId}/brain/export`,
      mental_models_ok: `${base}/v1/default/banks/${remoteBankId}/mental-models?limit=1`,
      memories_ok: `${base}/v1/default/banks/${remoteBankId}/memories/list?limit=1`,
      entities_ok: `${base}/v1/default/banks/${remoteBankId}/entities?limit=1`,
    };

    const capabilities = {
      version_ok: false,
      banks_ok: false,
      brain_export_ok: false,
      mental_models_ok: false,
      memories_ok: false,
      entities_ok: false,
      status_codes: {} as Record<string, number | null>,
    };

    await Promise.all(
      Object.entries(checks).map(async ([key, url]) => {
        const capKey = key as CapabilityKey;
        try {
          const resp = await fetch(url, { method: "GET", headers, cache: "no-store" });
          capabilities.status_codes[capKey] = resp.status;
          capabilities[capKey] = resp.status === 200;
        } catch {
          capabilities.status_codes[capKey] = null;
          capabilities[capKey] = false;
        }
      })
    );

    const recommended_learning_type = capabilities.brain_export_ok
      ? "distilled"
      : capabilities.memories_ok && (capabilities.mental_models_ok || capabilities.entities_ok)
        ? "structured"
        : capabilities.memories_ok
          ? "raw_mirror"
          : "auto";

    return NextResponse.json({ capabilities, recommended_learning_type }, { status: 200 });
  } catch (error) {
    console.error("Error probing remote capabilities:", error);
    return NextResponse.json({ error: "Failed to probe remote capabilities" }, { status: 500 });
  }
}
