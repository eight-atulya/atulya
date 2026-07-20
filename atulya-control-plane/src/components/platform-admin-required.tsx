import Link from "next/link";
import { ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";

export function PlatformAdminRequired() {
  return (
    <div className="mx-auto mt-10 max-w-xl rounded-lg border bg-card p-6 shadow-sm">
      <div className="flex items-start gap-4">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-muted">
          <ShieldAlert className="h-5 w-5 text-muted-foreground" />
        </div>
        <div>
          <h1 className="text-lg font-semibold">Platform admin access required</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            This page manages the whole Atulya deployment. Organization admins can manage users,
            service keys, grants, and audit for their own workspace.
          </p>
          <Button asChild className="mt-5">
            <Link href="/admin/api-keys">Manage organization access</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
