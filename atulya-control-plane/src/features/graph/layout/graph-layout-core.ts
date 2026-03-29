import { XYPosition } from "@xyflow/react";

export type WorkbenchSurfaceMode = "state" | "evidence";
export type GraphLayoutMode = "signal-first";
export type GraphHandleSide = "left" | "right" | "top" | "bottom";
export type GraphSourceHandleId = `source-${GraphHandleSide}`;
export type GraphTargetHandleId = `target-${GraphHandleSide}`;

export interface LayoutNodeInput {
  id: string;
  width: number;
  height: number;
  priority: number;
  pinnedPosition?: XYPosition | null;
}

export interface LayoutEdgeInput {
  id: string;
  source: string;
  target: string;
}

export interface LayoutGraphParams {
  surfaceMode: WorkbenchSurfaceMode;
  layoutMode: GraphLayoutMode;
  nodes: LayoutNodeInput[];
  edges: LayoutEdgeInput[];
  focalNodeId?: string | null;
}

export interface LayoutGraphResult {
  positions: Record<string, XYPosition>;
  handles: Record<
    string,
    {
      sourceSide: GraphHandleSide;
      targetSide: GraphHandleSide;
      sourceHandleId: GraphSourceHandleId;
      targetHandleId: GraphTargetHandleId;
    }
  >;
}

const TOP_PADDING = 72;
const LEFT_PADDING = 56;
const NODE_GAP = 28;

type Rect = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  pinned: boolean;
  priority: number;
};

export function toSourceHandleId(side: GraphHandleSide): GraphSourceHandleId {
  return `source-${side}`;
}

export function toTargetHandleId(side: GraphHandleSide): GraphTargetHandleId {
  return `target-${side}`;
}

function overlaps(a: Rect, b: Rect, gap = NODE_GAP) {
  return !(
    a.x + a.width + gap <= b.x ||
    b.x + b.width + gap <= a.x ||
    a.y + a.height + gap <= b.y ||
    b.y + b.height + gap <= a.y
  );
}

function resolveCollisions(rects: Rect[]) {
  const placed: Rect[] = [];

  rects
    .slice()
    .sort(
      (a, b) =>
        Number(b.pinned) - Number(a.pinned) || b.priority - a.priority || a.id.localeCompare(b.id)
    )
    .forEach((rect) => {
      const next = { ...rect };
      let guard = 0;

      while (guard < 400) {
        const blocking = placed.find((candidate) => overlaps(next, candidate));
        if (!blocking) break;

        if (next.pinned && !blocking.pinned) {
          blocking.y = next.y + next.height + NODE_GAP;
          guard += 1;
          continue;
        }

        next.y = blocking.y + blocking.height + NODE_GAP;
        guard += 1;
      }

      placed.push(next);
    });

  return placed;
}

function getHandlePair(source: Rect, target: Rect) {
  const sourceCenterX = source.x + source.width / 2;
  const sourceCenterY = source.y + source.height / 2;
  const targetCenterX = target.x + target.width / 2;
  const targetCenterY = target.y + target.height / 2;
  const deltaX = targetCenterX - sourceCenterX;
  const deltaY = targetCenterY - sourceCenterY;

  const pair: { sourceSide: GraphHandleSide; targetSide: GraphHandleSide } =
    Math.abs(deltaX) >= Math.abs(deltaY)
      ? deltaX >= 0
        ? { sourceSide: "right", targetSide: "left" }
        : { sourceSide: "left", targetSide: "right" }
      : deltaY >= 0
        ? { sourceSide: "bottom", targetSide: "top" }
        : { sourceSide: "top", targetSide: "bottom" };

  return {
    ...pair,
    sourceHandleId: toSourceHandleId(pair.sourceSide),
    targetHandleId: toTargetHandleId(pair.targetSide),
  };
}

function buildFallbackGrid(nodes: LayoutNodeInput[]) {
  const positions: Record<string, XYPosition> = {};
  const columns = Math.max(2, Math.min(4, Math.ceil(Math.sqrt(Math.max(nodes.length, 1)))));

  nodes.forEach((node, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    positions[node.id] = {
      x: LEFT_PADDING + column * 320,
      y: TOP_PADDING + row * 220,
    };
  });

  return positions;
}

function buildResultFromRects(
  rects: Rect[],
  edges: LayoutEdgeInput[],
  fallback: Record<string, XYPosition>
): LayoutGraphResult {
  const handles: LayoutGraphResult["handles"] = {};
  const rectMap = new Map(rects.map((rect) => [rect.id, rect]));

  edges.forEach((edge) => {
    const source = rectMap.get(edge.source);
    const target = rectMap.get(edge.target);
    if (!source || !target) return;
    handles[edge.id] = getHandlePair(source, target);
  });

  return {
    positions: Object.fromEntries(
      rects.map((rect) => [rect.id, { x: Math.round(rect.x), y: Math.round(rect.y) }])
    ),
    handles,
  };
}

export function buildFallbackLayout(params: LayoutGraphParams): LayoutGraphResult {
  const fallback = buildFallbackGrid(params.nodes);
  const rects = resolveCollisions(
    params.nodes.map((node) => ({
      id: node.id,
      x: node.pinnedPosition?.x ?? fallback[node.id]?.x ?? LEFT_PADDING,
      y: node.pinnedPosition?.y ?? fallback[node.id]?.y ?? TOP_PADDING,
      width: node.width,
      height: node.height,
      pinned: Boolean(node.pinnedPosition),
      priority: node.priority,
    }))
  );
  return buildResultFromRects(rects, params.edges, fallback);
}

export async function computeElkLayout(
  elk: { layout: (graph: any) => Promise<any> },
  params: LayoutGraphParams
): Promise<LayoutGraphResult> {
  const { surfaceMode, layoutMode, nodes, edges, focalNodeId } = params;
  const fallback = buildFallbackGrid(nodes);
  const layoutOptions =
    surfaceMode === "state"
      ? {
          "elk.algorithm": "layered",
          "elk.direction": "RIGHT",
          "elk.spacing.nodeNode": "52",
          "elk.layered.spacing.nodeNodeBetweenLayers": "108",
          "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
          "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
          "elk.padding": "[top=56,left=56,right=56,bottom=56]",
        }
      : {
          "elk.algorithm": "layered",
          "elk.direction": "RIGHT",
          "elk.spacing.nodeNode": "34",
          "elk.layered.spacing.nodeNodeBetweenLayers": "72",
          "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
          "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
          "elk.padding": "[top=48,left=48,right=48,bottom=48]",
        };

  const graph = (await elk.layout({
    id: "root",
    layoutOptions: {
      ...layoutOptions,
      "atulya.layoutMode": layoutMode,
    },
    children: nodes.map((node) => ({
      id: node.id,
      width: node.width,
      height: node.height,
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      sources: [edge.source],
      targets: [edge.target],
    })),
  })) as {
    children?: Array<{ id?: string; x?: number; y?: number }>;
  };

  const positions: Record<string, XYPosition> = { ...fallback };
  graph.children?.forEach((child) => {
    if (!child.id) return;
    positions[child.id] = {
      x: Math.round((child.x ?? 0) + LEFT_PADDING),
      y: Math.round((child.y ?? 0) + TOP_PADDING),
    };
  });

  if (focalNodeId && positions[focalNodeId]) {
    const focalPosition = positions[focalNodeId];
    const desiredFocal = surfaceMode === "state" ? { x: 300, y: 180 } : { x: 240, y: 160 };
    const deltaX = desiredFocal.x - focalPosition.x;
    const deltaY = desiredFocal.y - focalPosition.y;

    Object.keys(positions).forEach((nodeId) => {
      positions[nodeId] = {
        x: positions[nodeId].x + deltaX,
        y: positions[nodeId].y + deltaY,
      };
    });
  }

  const rects = resolveCollisions(
    nodes.map((node) => ({
      id: node.id,
      x: node.pinnedPosition?.x ?? positions[node.id]?.x ?? fallback[node.id].x,
      y: node.pinnedPosition?.y ?? positions[node.id]?.y ?? fallback[node.id].y,
      width: node.width,
      height: node.height,
      pinned: Boolean(node.pinnedPosition),
      priority: node.priority,
    }))
  );

  return buildResultFromRects(rects, edges, fallback);
}
