"use client";

import type { ReactNode } from "react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { HelpCircle } from "lucide-react";

export function TasteTooltip({
  content,
  children,
  side = "top",
}: {
  content: string;
  children: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side} className="max-w-xs text-center leading-snug">
        {content}
      </TooltipContent>
    </Tooltip>
  );
}

export function FieldLabel({
  label,
  hint,
  htmlFor,
}: {
  label: string;
  hint?: string;
  htmlFor?: string;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium leading-none">
        {label}
      </label>
      {hint ? (
        <TasteTooltip content={hint}>
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground"
            aria-label={`Help: ${label}`}
          >
            <HelpCircle className="h-3.5 w-3.5" />
          </button>
        </TasteTooltip>
      ) : null}
    </div>
  );
}

export function ToolbarSection({
  title,
  children,
  className,
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2 rounded-xl border border-border/60 bg-muted/30 px-3 py-2",
        className
      )}
    >
      <span className="mr-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </span>
      {children}
    </div>
  );
}

export function ScopePill({
  selectedCount,
  visibleCount,
  totalCount,
  transformScope,
}: {
  selectedCount: number;
  visibleCount: number;
  totalCount: number;
  transformScope: number;
}) {
  const label =
    selectedCount > 0
      ? `${selectedCount} selected`
      : transformScope > 0
        ? `All ${transformScope} sets in dataset`
        : "No sets yet";

  return (
    <div className="inline-flex items-center gap-2 rounded-full border bg-background/80 px-3 py-1 text-xs text-muted-foreground">
      <span className="font-medium text-foreground">{label}</span>
      {totalCount > 0 && (
        <span>
          · showing {visibleCount} of {totalCount}
        </span>
      )}
    </div>
  );
}

export function TasteStudioProvider({ children }: { children: ReactNode }) {
  return (
    <TooltipProvider delayDuration={300} skipDelayDuration={100}>
      {children}
    </TooltipProvider>
  );
}
