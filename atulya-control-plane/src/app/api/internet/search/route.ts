import { NextRequest, NextResponse } from "next/server";

const DEFAULT_SEARXNG = "http://127.0.0.1:18080";

function base(url: string): string {
  return url.replace(/\/$/, "");
}

/**
 * Server-side SearXNG JSON proxy for the Think UI (optional stack).
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const q = typeof body.query === "string" ? body.query.trim() : "";
    if (!q) {
      return NextResponse.json({ error: "query is required" }, { status: 400 });
    }

    const searxng = base(process.env.ATULYA_CP_INTERNET_SEARXNG_URL || DEFAULT_SEARXNG);
    const maxHits = Math.min(12, Math.max(1, parseInt(String(body.max_hits ?? 5), 10) || 5));

    const url = new URL(`${searxng}/search`);
    url.searchParams.set("q", q);
    url.searchParams.set("format", "json");

    const res = await fetch(url.toString(), {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(60_000),
    });

    if (!res.ok) {
      return NextResponse.json(
        { error: `SearXNG HTTP ${res.status}`, detail: await res.text().catch(() => "") },
        { status: 502 }
      );
    }

    const data = (await res.json()) as {
      results?: Array<{ title?: string; url?: string; content?: string }>;
    };
    const rows = (data.results || []).slice(0, maxHits);
    const lines: string[] = [];
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      const title = String(r.title || "")
        .replace(/\n/g, " ")
        .slice(0, 72);
      const u = String(r.url || "");
      const snip = String(r.content || "")
        .replace(/\n/g, " ")
        .slice(0, 140);
      if (u) {
        lines.push(`${i + 1}. ${title} | ${u}`);
        if (snip) lines.push(`   ${snip}`);
      }
    }
    const digest = lines.length ? lines.join("\n") : "(no hits)";

    return NextResponse.json({
      query: q,
      n: rows.length,
      digest,
      results: rows.map((r) => ({
        title: r.title ?? "",
        url: r.url ?? "",
        content: r.content ?? "",
      })),
    });
  } catch (e) {
    console.error("[internet/search]", e);
    return NextResponse.json({ error: "Search failed (is SearXNG up?)" }, { status: 503 });
  }
}
