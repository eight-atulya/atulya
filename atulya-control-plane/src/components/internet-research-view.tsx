"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useBank } from "@/lib/bank-context";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CopyButton } from "@/components/ui/copy-button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

type Budget = "low" | "mid" | "high";
type SearchHit = { title: string; url: string; content: string };
type ContentTab = "searxng" | "firecrawl";
type ClipSource = "searxng" | "firecrawl";
type ResearchClip = {
  id: string;
  title: string;
  url: string;
  source: ClipSource;
  query: string;
  content: string;
  note: string;
  created_at: string;
};
type RetainDraftPayload = {
  content: string;
  context?: string;
  timestamp?: string;
  document_id?: string;
  tags?: string[];
  observation_scopes?: "per_tag" | "combined" | "all_combinations" | string[][];
  metadata?: Record<string, string>;
  entities?: Array<{ text: string; type?: string }>;
};

export function InternetResearchView() {
  const { currentBank } = useBank();
  const [query, setQuery] = useState("");
  const [budget, setBudget] = useState<Budget>("mid");
  const [maxTokens, setMaxTokens] = useState<number>(4096);

  const [internetHealth, setInternetHealth] = useState<{
    searxng: { ok: boolean; base_url: string };
    firecrawl: { ok: boolean; base_url: string };
  } | null>(null);
  const [internetHealthLoading, setInternetHealthLoading] = useState(false);

  const [internetDigest, setInternetDigest] = useState<string | null>(null);
  const [searchResults, setSearchResults] = useState<SearchHit[]>([]);
  const [selectedUrl, setSelectedUrl] = useState<string | null>(null);
  const [extractMarkdown, setExtractMarkdown] = useState<string | null>(null);
  const [extractByUrl, setExtractByUrl] = useState<Record<string, string>>({});
  const [extractLoading, setExtractLoading] = useState(false);
  const [internetSearchLoading, setInternetSearchLoading] = useState(false);
  const [internetResearchLoading, setInternetResearchLoading] = useState(false);
  const [internetResearchResult, setInternetResearchResult] = useState<any>(null);
  const [internetError, setInternetError] = useState<string | null>(null);
  const [aiEnrichDraft, setAiEnrichDraft] = useState(false);
  const [aiEnrichLoading, setAiEnrichLoading] = useState(false);
  const [aiEnrichStatus, setAiEnrichStatus] = useState<string | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [modalHit, setModalHit] = useState<SearchHit | null>(null);
  const [modalTab, setModalTab] = useState<ContentTab>("searxng");
  const [clips, setClips] = useState<ResearchClip[]>([]);

  useEffect(() => {
    let cancelled = false;
    setInternetHealthLoading(true);
    fetch("/api/internet/health")
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled) setInternetHealth(data);
      })
      .catch(() => {
        if (!cancelled) setInternetHealth(null);
      })
      .finally(() => {
        if (!cancelled) setInternetHealthLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentBank]);

  const clipStorageKey = currentBank ? `internet:clipboard:${currentBank}` : null;

  useEffect(() => {
    if (!clipStorageKey || typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(clipStorageKey);
      if (!raw) {
        setClips([]);
        return;
      }
      const parsed = JSON.parse(raw) as ResearchClip[];
      setClips(Array.isArray(parsed) ? parsed : []);
    } catch {
      setClips([]);
    }
  }, [clipStorageKey]);

  useEffect(() => {
    if (!clipStorageKey || typeof window === "undefined") return;
    window.localStorage.setItem(clipStorageKey, JSON.stringify(clips));
  }, [clipStorageKey, clips]);

  const runInternetQuickSearch = async () => {
    if (!query.trim()) return;
    setInternetSearchLoading(true);
    setInternetError(null);
    setInternetDigest(null);
    setSearchResults([]);
    setSelectedUrl(null);
    setExtractMarkdown(null);
    setExtractByUrl({});
    try {
      const res = await fetch("/api/internet/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), max_hits: 6 }),
      });
      const data = await res.json();
      if (!res.ok) {
        setInternetError(typeof data.error === "string" ? data.error : "Search failed");
        return;
      }
      setInternetDigest(typeof data.digest === "string" ? data.digest : null);
      const rows = Array.isArray(data.results) ? (data.results as SearchHit[]) : [];
      setSearchResults(rows);
      if (rows.length > 0 && rows[0].url) {
        setSelectedUrl(rows[0].url);
      }
    } catch (e) {
      setInternetError(e instanceof Error ? e.message : "Search failed");
    } finally {
      setInternetSearchLoading(false);
    }
  };

  const runInternetResearch = async () => {
    if (!currentBank || !query.trim()) return;
    setInternetResearchLoading(true);
    setInternetError(null);
    setInternetResearchResult(null);
    try {
      const res = await fetch("/api/internet/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bank_id: currentBank,
          query: query.trim(),
          budget,
          max_tokens: maxTokens,
          include: { tool_calls: { output: true } },
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setInternetError(typeof data.error === "string" ? data.error : "Research failed");
        return;
      }
      setInternetResearchResult(data);
    } catch (e) {
      setInternetError(e instanceof Error ? e.message : "Research failed");
    } finally {
      setInternetResearchLoading(false);
    }
  };

  const runFirecrawlExtract = async (url: string) => {
    if (!url) return;
    if (extractByUrl[url]) {
      setSelectedUrl(url);
      setExtractMarkdown(extractByUrl[url]);
      return;
    }
    setSelectedUrl(url);
    setExtractLoading(true);
    setInternetError(null);
    setExtractMarkdown(null);
    try {
      const res = await fetch("/api/internet/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, max_chars: 2600 }),
      });
      const data = await res.json();
      if (!res.ok) {
        setInternetError(typeof data.error === "string" ? data.error : "Extract failed");
        return;
      }
      const md = typeof data.markdown === "string" ? data.markdown : "";
      setExtractMarkdown(md);
      setExtractByUrl((prev) => ({ ...prev, [url]: md }));
    } catch (e) {
      setInternetError(e instanceof Error ? e.message : "Extract failed");
    } finally {
      setExtractLoading(false);
    }
  };

  const openContentModal = async (hit: SearchHit) => {
    setModalHit(hit);
    setModalTab("searxng");
    setModalOpen(true);
    await runFirecrawlExtract(hit.url);
  };

  const addClip = (source: ClipSource) => {
    if (!modalHit) return;
    const content = source === "searxng" ? modalHit.content : extractByUrl[modalHit.url] || "";
    if (!content.trim()) return;
    const item: ResearchClip = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      title: modalHit.title || "(untitled)",
      url: modalHit.url,
      source,
      query: query.trim(),
      content,
      note: "",
      created_at: new Date().toISOString(),
    };
    setClips((prev) => [item, ...prev]);
  };

  const updateClipNote = (id: string, note: string) => {
    setClips((prev) => prev.map((c) => (c.id === id ? { ...c, note } : c)));
  };

  const removeClip = (id: string) => setClips((prev) => prev.filter((c) => c.id !== id));

  const combinedClipboard = clips
    .map((c, i) => {
      const header = `## Item ${i + 1} - ${c.title}\nSource: ${c.source.toUpperCase()} | URL: ${c.url}`;
      const note = c.note.trim() ? `\nCurator note: ${c.note.trim()}\n` : "\n";
      return `${header}${note}\n${c.content}`.trim();
    })
    .join("\n\n---\n\n");

  const buildRetainDraft = (): RetainDraftPayload | null => {
    if (!combinedClipboard.trim()) return null;
    const urls = Array.from(new Set(clips.map((c) => c.url).filter(Boolean)));
    const tagsFromDomains = urls
      .map((u) => {
        try {
          return new URL(u).hostname.replace(/^www\./, "").split(".")[0];
        } catch {
          return "";
        }
      })
      .filter(Boolean);
    const keywordPool = combinedClipboard.toLowerCase().match(/\b[a-z][a-z0-9-]{3,20}\b/g) || [];
    const stop = new Set([
      "this",
      "that",
      "with",
      "from",
      "into",
      "about",
      "their",
      "there",
      "where",
      "when",
      "have",
      "will",
      "were",
      "been",
      "http",
      "https",
      "www",
      "com",
      "org",
      "net",
      "research",
      "source",
      "content",
      "item",
    ]);
    const freq = new Map<string, number>();
    for (const w of keywordPool) {
      if (stop.has(w)) continue;
      freq.set(w, (freq.get(w) || 0) + 1);
    }
    const topKeywords = [...freq.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([k]) => k);
    const tags = Array.from(new Set([...tagsFromDomains, ...topKeywords])).slice(0, 12);

    const entityCandidates = Array.from(
      new Set((combinedClipboard.match(/\b[A-Z][a-zA-Z0-9.&-]{2,}\b/g) || []).slice(0, 20))
    );

    const metadata: Record<string, string> = {
      source: "internet_research_clipboard",
      clips_count: String(clips.length),
      urls_count: String(urls.length),
      query: query.trim(),
      generated_at: new Date().toISOString(),
    };

    return {
      content: combinedClipboard,
      context: query.trim()
        ? `Curated web research notes for query: "${query.trim()}". Review before retain.`
        : "Curated web research notes. Review before retain.",
      document_id: `internet-curation-${Date.now()}`,
      tags,
      observation_scopes: "combined",
      metadata,
      entities: entityCandidates.map((text) => ({ text })),
    };
  };

  const isValidTag = (t: unknown): t is string =>
    typeof t === "string" && !!t.trim() && t.length <= 32 && /^[a-zA-Z0-9:_-]+$/.test(t);

  const applyAiEnrichmentSafely = (
    base: RetainDraftPayload,
    enrichment: any
  ): { draft: RetainDraftPayload; accepted: boolean; reason: string } => {
    const confidence = Number(enrichment?.confidence ?? 0);
    if (!Number.isFinite(confidence) || confidence < 0.72) {
      return { draft: base, accepted: false, reason: "low confidence" };
    }

    const context = String(enrichment?.context || "").trim();
    if (context.length < 16 || context.length > 420) {
      return { draft: base, accepted: false, reason: "context quality gate failed" };
    }

    const tagsRaw: unknown[] = Array.isArray(enrichment?.tags) ? enrichment.tags : [];
    const tags: string[] = Array.from(
      new Set(tagsRaw.filter(isValidTag).map((t) => t.toLowerCase()))
    ).slice(0, 12);
    if (tags.length === 0) {
      return { draft: base, accepted: false, reason: "no valid tags" };
    }

    const baseTokens = new Set(
      (base.content.toLowerCase().match(/\b[a-z0-9:_-]{3,}\b/g) || []).slice(0, 1200)
    );
    const overlap = tags.filter((t) => baseTokens.has(t)).length;
    if (overlap === 0 && tags.length > 2) {
      return { draft: base, accepted: false, reason: "tag grounding check failed" };
    }

    const entitiesRaw: unknown[] = Array.isArray(enrichment?.entities) ? enrichment.entities : [];
    const entities: Array<{ text: string }> = Array.from(
      new Set(
        entitiesRaw
          .map((e: unknown) => String(e || "").trim())
          .filter((e: string) => e.length >= 2 && e.length <= 64)
      )
    )
      .slice(0, 25)
      .map((text) => ({ text }));

    const metadataCandidate = enrichment?.metadata;
    const metadata: Record<string, string> = { ...(base.metadata || {}) };
    if (
      metadataCandidate &&
      typeof metadataCandidate === "object" &&
      !Array.isArray(metadataCandidate)
    ) {
      for (const [k, v] of Object.entries(metadataCandidate as Record<string, unknown>)) {
        const key = String(k || "")
          .trim()
          .slice(0, 40);
        const value = String(v ?? "")
          .trim()
          .slice(0, 220);
        if (key && value) metadata[key] = value;
      }
    }
    metadata.ai_enriched = "true";
    metadata.ai_confidence = String(confidence.toFixed(2));

    const observation_scopes =
      enrichment?.observation_scopes === "per_tag" ? "per_tag" : ("combined" as const);

    return {
      draft: {
        ...base,
        context,
        tags,
        entities: entities.length > 0 ? entities : base.entities,
        metadata,
        observation_scopes,
      },
      accepted: true,
      reason: "accepted",
    };
  };

  const sendToRetainDraft = async () => {
    const payload = buildRetainDraft();
    if (!payload || !currentBank || typeof window === "undefined") return;

    let finalDraft = payload;
    setAiEnrichStatus(null);

    if (aiEnrichDraft) {
      setAiEnrichLoading(true);
      try {
        const res = await fetch("/api/internet/enrich-draft", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ bank_id: currentBank, draft: payload }),
        });
        const data = await res.json();
        if (res.ok && data?.enrichment) {
          const decision = applyAiEnrichmentSafely(payload, data.enrichment);
          finalDraft = decision.draft;
          setAiEnrichStatus(
            decision.accepted
              ? "AI enrich accepted (confidence checks passed)."
              : `AI enrich skipped (${decision.reason}), deterministic draft used.`
          );
        } else {
          setAiEnrichStatus("AI enrich unavailable, deterministic draft used.");
        }
      } catch {
        setAiEnrichStatus("AI enrich failed, deterministic draft used.");
      } finally {
        setAiEnrichLoading(false);
      }
    }

    const key = `retain:draft:pending:${currentBank}`;
    window.localStorage.setItem(key, JSON.stringify(finalDraft));
    window.dispatchEvent(
      new CustomEvent("atulya:retain-draft-ready", {
        detail: { bank_id: currentBank, storage_key: key },
      })
    );
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Internet backend controls</CardTitle>
          <CardDescription>
            Independent web workflow. This does not write to memory unless you explicitly retain
            data later.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-2 text-sm">
            {internetHealthLoading ? (
              <span>Checking backends...</span>
            ) : internetHealth ? (
              <>
                <span
                  className={
                    internetHealth.searxng?.ok
                      ? "text-emerald-600 dark:text-emerald-400"
                      : "text-amber-600"
                  }
                >
                  SearXNG {internetHealth.searxng?.ok ? "up" : "down"}
                </span>
                <span className="text-border">·</span>
                <span
                  className={
                    internetHealth.firecrawl?.ok
                      ? "text-emerald-600 dark:text-emerald-400"
                      : "text-muted-foreground"
                  }
                >
                  Firecrawl {internetHealth.firecrawl?.ok ? "up" : "optional"}
                </span>
              </>
            ) : (
              <span>Status unknown</span>
            )}
          </div>

          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Web question or keywords..."
              className="h-10 sm:flex-1"
              onKeyDown={(e) => e.key === "Enter" && runInternetQuickSearch()}
            />
            <Input
              value={maxTokens}
              type="number"
              onChange={(e) => setMaxTokens(parseInt(e.target.value, 10) || 4096)}
              className="h-10 w-32"
            />
            <select
              className="h-10 rounded-md border bg-background px-3 text-sm"
              value={budget}
              onChange={(e) => setBudget(e.target.value as Budget)}
            >
              <option value="low">low</option>
              <option value="mid">mid</option>
              <option value="high">high</option>
            </select>
          </div>

          <div className="flex gap-2">
            <Button
              type="button"
              variant="secondary"
              className="h-10"
              disabled={internetSearchLoading || !query.trim()}
              onClick={runInternetQuickSearch}
            >
              {internetSearchLoading ? "Searching..." : "Quick search"}
            </Button>
            <Button
              type="button"
              className="h-10"
              disabled={internetResearchLoading || !query.trim() || !internetHealth?.searxng?.ok}
              onClick={runInternetResearch}
            >
              {internetResearchLoading ? "Research..." : "Research (LLM)"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {internetError && <p className="text-sm text-destructive">{internetError}</p>}

      {internetDigest && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">SearXNG digest</CardTitle>
            <CardDescription>
              Raw metasearch ranking from SearXNG. Pick a result to compare Firecrawl extraction.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="max-h-64 overflow-auto rounded-md border bg-muted/40 p-3 text-xs whitespace-pre-wrap">
              {internetDigest}
            </pre>
          </CardContent>
        </Card>
      )}

      {searchResults.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">SearXNG results</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {searchResults.map((hit, index) => (
                <div
                  key={`${hit.url}-${index}`}
                  className={`w-full rounded-md border p-3 text-left transition ${
                    selectedUrl === hit.url ? "border-primary bg-primary/5" : "hover:bg-muted/40"
                  }`}
                >
                  <p className="text-sm font-medium">{hit.title || "(untitled)"}</p>
                  <p className="mt-1 text-xs text-muted-foreground break-all">{hit.url}</p>
                  {hit.content && (
                    <p className="mt-2 text-xs text-muted-foreground">{hit.content}</p>
                  )}
                  <div className="mt-3 flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={() => runFirecrawlExtract(hit.url)}
                    >
                      Extract
                    </Button>
                    <Button type="button" size="sm" onClick={() => openContentModal(hit)}>
                      Content
                    </Button>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Firecrawl extraction</CardTitle>
              <CardDescription>
                {selectedUrl
                  ? `Selected URL: ${selectedUrl}`
                  : "Select a SearXNG result to extract"}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {extractLoading ? (
                <p className="text-sm text-muted-foreground">Extracting page markdown...</p>
              ) : extractMarkdown ? (
                <div className="prose prose-sm dark:prose-invert max-w-none rounded-md border bg-muted/20 p-3">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{extractMarkdown}</ReactMarkdown>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No extraction loaded yet. Click a SearXNG result to fetch Firecrawl output.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Research clipboard</CardTitle>
          <CardDescription>
            Persistent in your browser for this bank. Collect multiple runs, curate notes, then copy
            final text for retain.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">{clips.length} collected item(s)</span>
            {combinedClipboard ? (
              <CopyButton text={combinedClipboard} toastLabel="Collected research copied" />
            ) : (
              <Button type="button" variant="outline" size="sm" disabled>
                Copy final collection
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={clips.length === 0}
              onClick={() => setClips([])}
            >
              Clear all
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!combinedClipboard || !currentBank || aiEnrichLoading}
              onClick={sendToRetainDraft}
            >
              {aiEnrichLoading ? "Preparing draft..." : "Send to Retain Draft"}
            </Button>
            <label className="ml-2 inline-flex items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={aiEnrichDraft}
                onChange={(e) => setAiEnrichDraft(e.target.checked)}
                className="h-4 w-4"
              />
              AI Enrich Draft (optional)
            </label>
          </div>
          {aiEnrichStatus && <p className="text-xs text-muted-foreground">{aiEnrichStatus}</p>}
          {clips.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No collected content yet. Use the Content button on a result and add SearXNG/Firecrawl
              content.
            </p>
          ) : (
            <div className="space-y-3">
              {clips.map((clip) => (
                <div key={clip.id} className="rounded-md border p-3">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{clip.title}</span>
                    <span>-</span>
                    <span>{clip.source.toUpperCase()}</span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground break-all">{clip.url}</p>
                  <Textarea
                    value={clip.note}
                    onChange={(e) => updateClipNote(clip.id, e.target.value)}
                    placeholder="Add your curation note for retain..."
                    className="mt-2 min-h-16"
                  />
                  <div className="mt-2 flex gap-2">
                    <CopyButton text={clip.content} toastLabel="Clip content copied" />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => removeClip(clip.id)}
                    >
                      Remove
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {internetResearchResult?.text && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Internet agent synthesis</CardTitle>
            <CardDescription>
              Agent-generated answer over web tools. Compare with the raw SearXNG + Firecrawl panes
              above.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {internetResearchResult.text}
              </ReactMarkdown>
            </div>
            {Array.isArray(internetResearchResult.source_urls) &&
              internetResearchResult.source_urls.length > 0 && (
                <ul className="mt-3 list-disc pl-5 text-sm text-muted-foreground">
                  {internetResearchResult.source_urls.map((u: string) => (
                    <li key={u}>
                      <a href={u} className="underline break-all" target="_blank" rel="noreferrer">
                        {u}
                      </a>
                    </li>
                  ))}
                </ul>
              )}
          </CardContent>
        </Card>
      )}

      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="max-w-5xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Content inspector</DialogTitle>
            <DialogDescription>
              Compare direct SearXNG snippet and Firecrawl extracted content before collecting into
              clipboard.
            </DialogDescription>
          </DialogHeader>
          {modalHit && (
            <div className="space-y-4">
              <p className="text-sm font-medium">{modalHit.title || "(untitled)"}</p>
              <p className="text-xs text-muted-foreground break-all">{modalHit.url}</p>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant={modalTab === "searxng" ? "default" : "outline"}
                  onClick={() => setModalTab("searxng")}
                >
                  SearXNG
                </Button>
                <Button
                  type="button"
                  variant={modalTab === "firecrawl" ? "default" : "outline"}
                  onClick={() => setModalTab("firecrawl")}
                >
                  Firecrawl
                </Button>
              </div>

              {modalTab === "searxng" ? (
                <div className="space-y-3">
                  <div className="rounded-md border bg-muted/20 p-3">
                    <p className="text-sm whitespace-pre-wrap">
                      {modalHit.content || "(empty snippet)"}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <CopyButton text={modalHit.content || ""} toastLabel="SearXNG snippet copied" />
                    <Button
                      type="button"
                      onClick={() => addClip("searxng")}
                      disabled={!modalHit.content?.trim()}
                    >
                      Add to clipboard
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  {!extractByUrl[modalHit.url] ? (
                    <Button
                      type="button"
                      onClick={() => runFirecrawlExtract(modalHit.url)}
                      disabled={extractLoading}
                    >
                      {extractLoading ? "Extracting..." : "Fetch Firecrawl content"}
                    </Button>
                  ) : (
                    <>
                      <div className="prose prose-sm dark:prose-invert max-w-none rounded-md border bg-muted/20 p-3">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {extractByUrl[modalHit.url]}
                        </ReactMarkdown>
                      </div>
                      <div className="flex gap-2">
                        <CopyButton
                          text={extractByUrl[modalHit.url]}
                          toastLabel="Firecrawl content copied"
                        />
                        <Button type="button" onClick={() => addClip("firecrawl")}>
                          Add to clipboard
                        </Button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
