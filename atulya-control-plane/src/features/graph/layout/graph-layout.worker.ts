/// <reference lib="webworker" />

import ELK from "elkjs/lib/elk-api.js";

import { computeElkLayout, LayoutGraphParams, LayoutGraphResult } from "./graph-layout-core";

type LayoutWorkerRequest = {
  id: number;
  params: LayoutGraphParams;
};

type LayoutWorkerResponse = {
  id: number;
  result?: LayoutGraphResult;
  error?: string;
};

function createElk() {
  return new ELK({
    workerFactory: () =>
      new Worker(new URL("./elk-runtime.worker.ts", import.meta.url), { type: "module" }),
  });
}

const elk = createElk();
const ctx: DedicatedWorkerGlobalScope = self as DedicatedWorkerGlobalScope;

ctx.onmessage = async (event: MessageEvent<LayoutWorkerRequest>) => {
  try {
    const result = await computeElkLayout(elk, event.data.params);
    const response: LayoutWorkerResponse = {
      id: event.data.id,
      result,
    };
    ctx.postMessage(response);
  } catch (error) {
    const response: LayoutWorkerResponse = {
      id: event.data.id,
      error: error instanceof Error ? error.message : "Layout worker failed",
    };
    ctx.postMessage(response);
  }
};
