"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";

export function AdminButton() {
  const router = useRouter();
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    fetch("/api/auth/me", { cache: "no-store" })
      .then(async (response) => (response.ok ? response.json() : null))
      .then((identity) => {
        const actions = new Set<string>(identity?.allowed_actions || []);
        setVisible(
          Array.from(actions).some((action) => action.startsWith("admin.")) ||
            actions.has("system.admin")
        );
      })
      .catch(() => setVisible(false));
  }, []);

  if (!visible) return null;
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={async () => {
        const response = await fetch("/api/auth/me", { cache: "no-store" });
        const identity = response.ok ? await response.json() : null;
        router.push(identity?.active_org_id ? "/admin" : "/admin/platform");
      }}
      className="h-9 gap-1.5 text-muted-foreground hover:text-foreground"
      title="Organization administration"
    >
      <ShieldCheck className="h-4 w-4" />
      <span className="text-sm font-medium">Admin</span>
    </Button>
  );
}
