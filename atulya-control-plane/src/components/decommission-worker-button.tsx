"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

export function DecommissionWorkerButton({
  workerId,
  schema,
  label,
}: {
  workerId: string;
  schema: string;
  label?: string;
}) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const run = async () => {
    setLoading(true);
    try {
      const response = await fetch(
        `/api/admin-control/workers/${encodeURIComponent(workerId)}/decommission?schema=${encodeURIComponent(schema)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ release_stuck: true }),
        }
      );
      const body = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(
          body?.detail?.message || body?.detail?.code || body?.detail || "Recovery failed"
        );
      toast.success(`${body.released_count || 0} operations released`);
      router.refresh();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Recovery failed");
    } finally {
      setLoading(false);
    }
  };
  return (
    <Button
      size={label ? "sm" : "icon"}
      variant="outline"
      title={label || "Release worker operations"}
      disabled={loading}
      onClick={() => void run()}
    >
      <RefreshCw
        className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""} ${label ? "mr-2" : ""}`}
      />
      {label}
    </Button>
  );
}
