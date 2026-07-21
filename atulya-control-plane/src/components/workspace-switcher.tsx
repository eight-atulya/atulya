"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Building2, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { CurrentIdentity } from "@/lib/server-auth";

function slugify(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

export function WorkspaceSwitcher({ identity: initialIdentity }: { identity?: CurrentIdentity }) {
  const router = useRouter();
  const [identity, setIdentity] = useState<CurrentIdentity | null>(initialIdentity || null);
  const [switching, setSwitching] = useState(false);
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const slug = useMemo(() => slugify(name), [name]);

  useEffect(() => {
    if (initialIdentity) return;
    fetch("/api/auth/me", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((value) => setIdentity(value))
      .catch(() => setIdentity(null));
  }, [initialIdentity]);

  if (!identity) return null;

  const createWorkspace = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCreating(true);
    try {
      const response = await fetch("/api/workspaces", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), slug }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = body?.detail;
        throw new Error(
          typeof detail === "string" ? detail : detail?.code || "Workspace creation failed"
        );
      }
      const switched = await fetch("/api/auth/switch-workspace", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ org_id: body.id }),
      });
      if (!switched.ok) throw new Error("Workspace created, but switching failed");
      toast.success("Workspace created");
      setOpen(false);
      setName("");
      router.push("/dashboard");
      router.refresh();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Workspace creation failed");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex h-8 min-w-0 items-center rounded-md border bg-background">
      <div className="relative flex h-full min-w-0 items-center">
        {switching ? (
          <Loader2 className="ml-2.5 h-3.5 w-3.5 animate-spin text-muted-foreground" />
        ) : (
          <Building2 className="ml-2.5 h-3.5 w-3.5 text-muted-foreground" />
        )}
        {identity.memberships.length > 1 ? (
          <select
            aria-label="Active workspace"
            className="h-full max-w-52 appearance-none bg-transparent py-0 pl-2 pr-7 text-xs outline-none"
            value={identity.active_org_id || ""}
            disabled={switching}
            onChange={async (event) => {
              setSwitching(true);
              const response = await fetch("/api/auth/switch-workspace", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ org_id: event.target.value }),
              });
              if (response.ok) {
                router.push("/dashboard");
                router.refresh();
              } else {
                toast.error("Could not switch workspace");
                setSwitching(false);
              }
            }}
          >
            {identity.memberships.map((membership) => (
              <option key={membership.org_id} value={membership.org_id}>
                {membership.org_name}
              </option>
            ))}
          </select>
        ) : (
          <span className="max-w-40 truncate px-2 text-xs">
            {identity.org_name || identity.org_slug || "No workspace"}
          </span>
        )}
      </div>
      {identity.principal_type === "user" && identity.email_verified && (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7 rounded-l-none border-l"
              title="Create workspace"
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create workspace</DialogTitle>
            </DialogHeader>
            <form className="space-y-4" onSubmit={(event) => void createWorkspace(event)}>
              <div>
                <Label htmlFor="new-workspace-name">Workspace name</Label>
                <Input
                  id="new-workspace-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  minLength={2}
                  maxLength={160}
                  required
                  autoFocus
                  className="mt-1.5"
                />
                {name && <p className="mt-1.5 text-xs text-muted-foreground">Slug: {slug}</p>}
              </div>
              <Button className="w-full" type="submit" disabled={creating || slug.length < 2}>
                {creating && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Create workspace
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
