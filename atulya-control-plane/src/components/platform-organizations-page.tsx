"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Building2, Database, Loader2, Plus, RefreshCw, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
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

type Organization = {
  id: string;
  slug: string;
  name: string;
  schema_name: string;
  status: string;
  created_at: string;
};
type Tenant = { schema_name: string; bank_count: number };
type Bank = { bank_id: string; name: string; created_at: string; updated_at: string };

async function platform<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/admin-control${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail?.message || detail?.code || `HTTP ${response.status}`
    );
  }
  return body as T;
}

export function PlatformOrganizationsPage() {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [banks, setBanks] = useState<{ org: Organization; rows: Bank[] } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [orgRows, tenantRows] = await Promise.all([
        platform<Organization[]>("/orgs"),
        platform<Tenant[]>("/tenants"),
      ]);
      setOrganizations(orgRows);
      setTenants(tenantRows);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Platform data unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await platform("/orgs", {
        method: "POST",
        body: JSON.stringify({
          slug: form.get("slug"),
          name: form.get("name"),
          owner_email: form.get("owner_email"),
          owner_name: form.get("owner_name") || null,
        }),
      });
      toast.success("Organization provisioned");
      setOpen(false);
      await load();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Provisioning failed");
    }
  };

  const setStatus = async (org: Organization, status: "active" | "disabled") => {
    if (status === "disabled" && !window.confirm(`Disable ${org.name} and revoke its sessions?`))
      return;
    try {
      await platform(`/orgs/${org.id}?status=${status}`, { method: "PATCH", body: "{}" });
      toast.success(status === "active" ? "Organization enabled" : "Organization disabled");
      await load();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Status update failed");
    }
  };

  const inspect = async (org: Organization) => {
    try {
      setBanks({ org, rows: await platform<Bank[]>(`/tenants/${org.schema_name}/banks`) });
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Bank inspection failed");
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 border-b pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Organizations</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Provisioning state, tenant schemas, and memory-bank inventory.
          </p>
        </div>
        <div className="flex gap-2">
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="mr-2 h-4 w-4" />
                Provision organization
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Provision organization</DialogTitle>
              </DialogHeader>
              <form className="space-y-4" onSubmit={(event) => void create(event)}>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <Label htmlFor="platform-org-name">Name</Label>
                    <Input id="platform-org-name" name="name" required className="mt-1.5" />
                  </div>
                  <div>
                    <Label htmlFor="platform-org-slug">Slug</Label>
                    <Input id="platform-org-slug" name="slug" required className="mt-1.5" />
                  </div>
                </div>
                <div>
                  <Label htmlFor="platform-owner-email">Verified owner email</Label>
                  <Input
                    id="platform-owner-email"
                    name="owner_email"
                    type="email"
                    required
                    className="mt-1.5"
                  />
                </div>
                <div>
                  <Label htmlFor="platform-owner-name">Owner name</Label>
                  <Input id="platform-owner-name" name="owner_name" className="mt-1.5" />
                </div>
                <Button className="w-full" type="submit">
                  Provision organization
                </Button>
              </form>
            </DialogContent>
          </Dialog>
          <Button variant="outline" size="icon" title="Refresh" onClick={() => void load()}>
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {loading && (
        <div className="flex min-h-48 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      )}
      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm">
          {error}
        </div>
      )}
      {!loading && !error && (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full min-w-[820px] text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Organization</th>
                <th className="px-4 py-3">Schema</th>
                <th className="px-4 py-3">Banks</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {organizations.map((org) => (
                <tr key={org.id} className="border-t">
                  <td className="px-4 py-3">
                    <p className="font-medium">{org.name}</p>
                    <p className="text-xs text-muted-foreground">{org.slug}</p>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">{org.schema_name}</td>
                  <td className="px-4 py-3 tabular-nums">
                    {tenants.find((tenant) => tenant.schema_name === org.schema_name)?.bank_count ??
                      0}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={org.status === "active" ? "default" : "secondary"}>
                      {org.status}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        size="icon"
                        variant="ghost"
                        title="Inspect memory banks"
                        onClick={() => void inspect(org)}
                      >
                        <Database className="h-4 w-4" />
                      </Button>
                      {org.status === "failed" ? (
                        <Button
                          size="icon"
                          variant="ghost"
                          title="Retry provisioning"
                          onClick={async () => {
                            await platform(`/orgs/${org.id}/retry-provisioning`, {
                              method: "POST",
                              body: "{}",
                            });
                            toast.success("Provisioning retried");
                            await load();
                          }}
                        >
                          <RotateCcw className="h-4 w-4" />
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            void setStatus(org, org.status === "active" ? "disabled" : "active")
                          }
                        >
                          {org.status === "active" ? "Disable" : "Enable"}
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!organizations.length && (
            <p className="p-8 text-center text-sm text-muted-foreground">No organizations.</p>
          )}
        </div>
      )}

      <Dialog open={Boolean(banks)} onOpenChange={(value) => !value && setBanks(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{banks?.org.name} memory banks</DialogTitle>
          </DialogHeader>
          <div className="max-h-80 overflow-auto rounded-md border">
            {banks?.rows.map((bank) => (
              <div
                key={bank.bank_id}
                className="flex items-center gap-3 border-b px-3 py-2.5 last:border-0"
              >
                <Building2 className="h-4 w-4 text-muted-foreground" />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{bank.name}</p>
                  <p className="truncate font-mono text-[11px] text-muted-foreground">
                    {bank.bank_id}
                  </p>
                </div>
              </div>
            ))}
            {banks && !banks.rows.length && (
              <p className="p-6 text-center text-sm text-muted-foreground">No memory banks.</p>
            )}
          </div>
          {banks && banks.rows.length > 0 && (
            <Button
              variant="outline"
              onClick={async () => {
                const result = await platform<{ queued_count: number }>(
                  `/consolidate/${banks.org.schema_name}`,
                  { method: "POST", body: "{}" }
                );
                toast.success(`${result.queued_count} consolidation operations queued`);
              }}
            >
              Consolidate all banks
            </Button>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
