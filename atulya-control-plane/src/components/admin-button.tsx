"use client";

/**
 * AdminButton
 *
 * Renders a shield icon button in the main header.
 * On click: checks /api/admin-access (server-side env check, never exposes
 * the key), then either navigates to /admin or shows an access error toast.
 *
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldCheck, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

export function AdminButton() {
  const router = useRouter();
  const [checking, setChecking] = useState(false);

  const handleClick = async () => {
    setChecking(true);
    try {
      const res = await fetch("/api/admin-access");
      const { enabled } = (await res.json()) as { enabled: boolean };

      if (enabled) {
        router.push("/admin");
      } else {
        toast.error("Admin access not configured", {
          description: "Set ATULYA_CP_ADMIN_API_KEY in .env.local and restart.",
          duration: 5000,
        });
      }
    } catch {
      toast.error("Could not check admin access");
    } finally {
      setChecking(false);
    }
  };

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={handleClick}
      disabled={checking}
      className="h-9 gap-1.5 text-muted-foreground hover:text-foreground"
      title="Go to Admin Panel"
    >
      {checking ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <ShieldCheck className="h-4 w-4" />
      )}
      <span className="text-sm font-medium">Admin</span>
    </Button>
  );
}
