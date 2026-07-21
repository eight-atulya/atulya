/**
 * Entity co-occurrence graph — derived from atulya's memory graph.
 *
 * ROOT CAUSE: Hindsight has a materialised `entity_cooccurrences` table
 * populated during every retain.  Atulya does NOT have this table.
 * `getGraphIntelligence` (graph/intelligence) is a separate computed feature
 * that is empty right after ingest.
 *
 * SOLUTION: Derive entity co-occurrence dynamically:
 *   1. Fetch memory nodes via GET /graph — each node.data.entities is
 *      "Alice (PERSON), Google (ORG)" listing all entities in that memory.
 *   2. Fetch entity list for UUID + mention_count + last_seen.
 *   3. For every pair of entities sharing the same memory → co-occurrence +1.
 *   4. Return nodes + edges in the constellation.convertEntityGraphData() shape
 *      (identical to hindsight's entity_graph response).
 *
 * Confidence: high — two stable SDK methods (getGraph + listEntities).
 *
 */

import { NextRequest, NextResponse } from "next/server";
import { sdk, createLowLevelClientForRequest } from "@/lib/atulya-client";

const NODE_COLOURS = [
  "#8b5cf6",
  "#ec4899",
  "#6366f1",
  "#f59e0b",
  "#10b981",
  "#3b82f6",
  "#ef4444",
  "#06b6d4",
  "#f97316",
  "#a855f7",
  "#14b8a6",
  "#eab308",
];

interface EntityRecord {
  id: string;
  canonical_name: string;
  mention_count: number;
  last_seen: string | null;
}

/** Parse "Alice (PERSON), Google (ORG)" → ["alice", "google"] (lowercase for map keying) */
function parseEntityNames(entitiesStr: string): string[] {
  if (!entitiesStr || entitiesStr === "None") return [];
  return entitiesStr
    .split(",")
    .map((e) => e.replace(/\s*\([^)]*\)/g, "").trim())
    .filter(Boolean);
}

const EMPTY_GRAPH = { nodes: [], edges: [], total_entities: 0, total_edges: 0, limit: 2000 };

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const bankId = searchParams.get("bank_id");
  if (!bankId) {
    return NextResponse.json({ error: "bank_id is required" }, { status: 400 });
  }

  const limit = Math.min(Number(searchParams.get("limit") || "2000"), 2000);
  const minCount = Number(searchParams.get("min_count") || "1");

  try {
    // [branch] Parallel: memory graph (entity lists per node) + entity registry (IDs)
    const [graphRes, entitiesRes] = await Promise.all([
      sdk.getGraph({
        client: createLowLevelClientForRequest(request),
        path: { bank_id: bankId },
        query: { limit: 2000 } as Record<string, unknown>,
      }),
      sdk.listEntities({
        client: createLowLevelClientForRequest(request),
        path: { bank_id: bankId },
        query: { limit: 500, offset: 0 } as Record<string, unknown>,
      }),
    ]);

    const entityList: EntityRecord[] =
      (entitiesRes.data as { items?: any[] } | undefined)?.items?.map((e: any) => ({
        id: String(e.id),
        canonical_name: e.canonical_name,
        mention_count: e.mention_count || 1,
        last_seen: e.last_seen || null,
      })) ?? [];

    if (entityList.length === 0) {
      return NextResponse.json(EMPTY_GRAPH, { status: 200 });
    }

    // [branch] Build name → entity index (lowercase for fuzzy matching)
    const entityByName = new Map<string, EntityRecord>();
    for (const e of entityList) {
      entityByName.set(e.canonical_name.toLowerCase(), e);
    }

    // [branch] Scan memory nodes, count entity-pair co-occurrences
    type CoData = { count: number; lastSeen: string | null };
    const cooccurrence = new Map<string, CoData>();
    const graphNodes = (graphRes.data as { nodes?: any[] } | undefined)?.nodes ?? [];

    for (const node of graphNodes) {
      const names = parseEntityNames(node?.data?.entities ?? "");
      if (names.length < 2) continue;

      const resolved = names
        .map((n) => entityByName.get(n.toLowerCase()))
        .filter((e): e is EntityRecord => e !== undefined);

      if (resolved.length < 2) continue;

      // All entity pairs within this memory are co-occurring
      for (let i = 0; i < resolved.length; i++) {
        for (let j = i + 1; j < resolved.length; j++) {
          const key = [resolved[i].id, resolved[j].id].sort().join("|");
          const prev = cooccurrence.get(key) ?? { count: 0, lastSeen: null };
          prev.count += 1;
          // Track most recent memory mention as lastCooccurred
          const mentionAt: string | null = node?.data?.date
            ? new Date(node.data.date).toISOString()
            : null;
          if (mentionAt && (!prev.lastSeen || mentionAt > prev.lastSeen)) {
            prev.lastSeen = mentionAt;
          }
          cooccurrence.set(key, prev);
        }
      }
    }

    // [leaf] Build output — filter by minCount, cap at limit, sort by weight
    const usedIds = new Set<string>();
    const edges: any[] = [];

    const sorted = Array.from(cooccurrence.entries()).sort((a, b) => b[1].count - a[1].count);

    for (const [key, { count, lastSeen }] of sorted) {
      if (count < minCount) continue;
      if (edges.length >= limit) break;
      const [idA, idB] = key.split("|");
      usedIds.add(idA);
      usedIds.add(idB);
      edges.push({
        data: {
          id: `${idA}-${idB}`,
          source: idA,
          target: idB,
          linkType: "cooccurrence",
          weight: count,
          color: "#ffd700",
          lineStyle: "solid",
          lastCooccurred: lastSeen,
        },
      });
    }

    const entityById = new Map(entityList.map((e, i) => [e.id, { ...e, idx: i }]));
    const nodes = Array.from(usedIds).map((id) => {
      const ent = entityById.get(id);
      return {
        data: {
          id,
          label: ent?.canonical_name ?? id,
          mentionCount: ent?.mention_count ?? 1,
          color: NODE_COLOURS[(ent?.idx ?? 0) % NODE_COLOURS.length],
        },
      };
    });

    return NextResponse.json(
      { nodes, edges, total_entities: nodes.length, total_edges: edges.length, limit },
      { status: 200 }
    );
  } catch (error) {
    console.error("Error building entity co-occurrence graph:", error);
    return NextResponse.json(EMPTY_GRAPH, { status: 200 });
  }
}
