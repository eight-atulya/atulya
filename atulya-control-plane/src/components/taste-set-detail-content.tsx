"use client";

import { useMemo, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import type { TasteSetItem } from "@/lib/api";
import { diffJson } from "@/lib/taste-templates";

interface TasteSetDetailContentProps {
  tasteSet: TasteSetItem;
  editable?: boolean;
  draftJson?: string;
  onDraftChange?: (value: string) => void;
}

export function TasteSetDetailContent({
  tasteSet,
  editable = false,
  draftJson,
  onDraftChange,
}: TasteSetDetailContentProps) {
  const [tab, setTab] = useState("working");
  const workingPretty = useMemo(
    () => JSON.stringify(tasteSet.working_payload, null, 2),
    [tasteSet.working_payload]
  );
  const seedPretty = useMemo(
    () => JSON.stringify(tasteSet.source_payload, null, 2),
    [tasteSet.source_payload]
  );
  const diffText = useMemo(
    () => diffJson(tasteSet.source_payload, tasteSet.working_payload),
    [tasteSet.source_payload, tasteSet.working_payload]
  );

  return (
    <div className="space-y-4">
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="working">Working</TabsTrigger>
          <TabsTrigger value="seed">Seed</TabsTrigger>
          <TabsTrigger value="diff">Diff</TabsTrigger>
          <TabsTrigger value="lineage">Lineage</TabsTrigger>
        </TabsList>
        <p className="mt-2 text-xs text-muted-foreground">
          {tab === "working" && "Editable copy — what gets exported after you save."}
          {tab === "seed" && "Immutable import anchor — use Revert to restore."}
          {tab === "diff" && "Changes between seed and working payload."}
          {tab === "lineage" && "Parent variants, memory links, and transform history."}
        </p>
        <TabsContent value="working" className="mt-3">
          {editable ? (
            <Textarea
              className="min-h-[320px] font-mono text-xs"
              value={draftJson ?? workingPretty}
              onChange={(e) => onDraftChange?.(e.target.value)}
            />
          ) : (
            <pre className="max-h-[420px] overflow-auto rounded-md border bg-muted/30 p-3 text-xs">
              {workingPretty}
            </pre>
          )}
        </TabsContent>
        <TabsContent value="seed" className="mt-3">
          <pre className="max-h-[420px] overflow-auto rounded-md border bg-muted/30 p-3 text-xs">
            {seedPretty}
          </pre>
        </TabsContent>
        <TabsContent value="diff" className="mt-3">
          <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-3 text-xs">
            {diffText}
          </pre>
        </TabsContent>
        <TabsContent value="lineage" className="mt-3 space-y-2 text-sm">
          <p>
            <span className="text-muted-foreground">Set key:</span> {tasteSet.set_key}
          </p>
          {tasteSet.parent_set_id && (
            <p>
              <span className="text-muted-foreground">Parent:</span> {tasteSet.parent_set_id}
            </p>
          )}
          {tasteSet.memory_unit_ids && tasteSet.memory_unit_ids.length > 0 && (
            <div>
              <p className="text-muted-foreground">Memory units</p>
              <ul className="mt-1 list-inside list-disc font-mono text-xs">
                {tasteSet.memory_unit_ids.map((id) => (
                  <li key={id}>{id}</li>
                ))}
              </ul>
            </div>
          )}
          {(tasteSet.transform_log?.length ?? 0) > 0 && (
            <div>
              <p className="text-muted-foreground">Transform log</p>
              <pre className="mt-1 max-h-48 overflow-auto rounded-md border bg-muted/30 p-2 text-xs">
                {JSON.stringify(tasteSet.transform_log, null, 2)}
              </pre>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
