"use client";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { TasteSetItem } from "@/lib/api";
import { ChevronRight, Loader2, RotateCcw, Save } from "lucide-react";
import { TasteSetDetailContent } from "./taste-set-detail-content";
import { TasteTooltip } from "./taste-studio-ui";

interface TasteSetDetailPanelProps {
  tasteSet: TasteSetItem;
  draftJson: string;
  saving?: boolean;
  onDraftChange: (value: string) => void;
  onSave: () => void;
  onRevert: () => void;
  onClose: () => void;
}

export function TasteSetDetailPanel({
  tasteSet,
  draftJson,
  saving,
  onDraftChange,
  onSave,
  onRevert,
  onClose,
}: TasteSetDetailPanelProps) {
  return (
    <aside
      className="absolute inset-y-0 right-0 z-20 flex w-full max-w-[min(52%,540px)] flex-col border-l border-border/80 bg-card/98 shadow-2xl backdrop-blur-md animate-in slide-in-from-right duration-300"
      role="dialog"
      aria-label={`Inspect ${tasteSet.set_key}`}
    >
      <div className="flex items-start justify-between gap-3 border-b border-border/60 px-5 py-4">
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={onClose}
            className="mb-2 flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <ChevronRight className="h-3.5 w-3.5 rotate-180" />
            Back to table
          </button>
          <h2 className="truncate text-lg font-semibold">{tasteSet.set_key}</h2>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge variant={tasteSet.variant_index === 0 ? "default" : "secondary"}>
              {tasteSet.variant_index === 0 ? "seed" : `v${tasteSet.variant_index}`}
            </Badge>
            <Badge variant="outline">{tasteSet.status}</Badge>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <TasteTooltip content="Reset working copy to the immutable seed payload">
            <Button variant="outline" size="sm" onClick={onRevert} disabled={saving}>
              <RotateCcw className="mr-1.5 h-4 w-4" />
              Revert
            </Button>
          </TasteTooltip>
          <TasteTooltip content="Save working payload and mark set as ready">
            <Button size="sm" onClick={onSave} disabled={saving}>
              {saving ? (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-1.5 h-4 w-4" />
              )}
              Save
            </Button>
          </TasteTooltip>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <TasteSetDetailContent
          tasteSet={tasteSet}
          editable
          draftJson={draftJson}
          onDraftChange={onDraftChange}
        />
      </div>
    </aside>
  );
}
