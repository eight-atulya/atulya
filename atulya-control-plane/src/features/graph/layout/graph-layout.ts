"use client";

import {
  buildFallbackLayout,
  GraphHandleSide,
  GraphLayoutMode,
  GraphSourceHandleId,
  GraphTargetHandleId,
  LayoutEdgeInput,
  LayoutGraphParams,
  LayoutGraphResult,
  LayoutNodeInput,
  WorkbenchSurfaceMode,
  toSourceHandleId,
  toTargetHandleId,
} from "./graph-layout-core";

export type {
  GraphHandleSide,
  GraphLayoutMode,
  GraphSourceHandleId,
  GraphTargetHandleId,
  LayoutEdgeInput,
  LayoutGraphParams,
  LayoutGraphResult,
  LayoutNodeInput,
  WorkbenchSurfaceMode,
};

type LayoutWorkerRequest = {
  id: number;
  params: LayoutGraphParams;
};

type LayoutWorkerResponse = {
  id: number;
  result?: LayoutGraphResult;
  error?: string;
};

let workerInstance: Worker | null = null;
let requestId = 0;
const pendingRequests = new Map<
  number,
  {
    resolve: (result: LayoutGraphResult) => void;
    reject: (error: Error) => void;
  }
>();

function getWorker() {
  if (typeof window === "undefined") {
    return null;
  }
  if (workerInstance) {
    return workerInstance;
  }

  workerInstance = new Worker(new URL("./graph-layout.worker.ts", import.meta.url));
  workerInstance.onmessage = (event: MessageEvent<LayoutWorkerResponse>) => {
    const pending = pendingRequests.get(event.data.id);
    if (!pending) {
      return;
    }
    pendingRequests.delete(event.data.id);
    if (event.data.result) {
      pending.resolve(event.data.result);
      return;
    }
    pending.reject(new Error(event.data.error || "Layout worker failed"));
  };
  workerInstance.onerror = () => {
    pendingRequests.forEach(({ reject }) => reject(new Error("Layout worker crashed")));
    pendingRequests.clear();
    workerInstance?.terminate();
    workerInstance = null;
  };

  return workerInstance;
}

export function terminateGraphLayoutWorker() {
  if (workerInstance) {
    workerInstance.terminate();
    workerInstance = null;
  }
  pendingRequests.forEach(({ reject }) => reject(new Error("Layout worker terminated")));
  pendingRequests.clear();
}

export async function layoutGraph(params: LayoutGraphParams): Promise<LayoutGraphResult> {
  const worker = getWorker();
  if (!worker) {
    return buildFallbackLayout(params);
  }

  const id = ++requestId;
  return await new Promise<LayoutGraphResult>((resolve, reject) => {
    pendingRequests.set(id, { resolve, reject });
    const message: LayoutWorkerRequest = {
      id,
      params,
    };
    worker.postMessage(message);
  }).catch(() => buildFallbackLayout(params));
}

export { toSourceHandleId, toTargetHandleId };
