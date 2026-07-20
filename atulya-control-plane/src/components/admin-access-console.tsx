"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import type React from "react";
import {
  Copy,
  KeyRound,
  Loader2,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UserPlus,
} from "lucide-react";
import { toast } from "sonner";
import type {
  AccessGrantResponse,
  ApiKeyResponse,
  AuditEventResponse,
  OrgResponse,
  PrincipalResponse,
} from "@/lib/admin-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const ACTIONS = [
  "bank.read",
  "bank.write",
  "bank.delete",
  "bank.config",
  "memory.retain",
  "memory.recall",
  "memory.delete",
  "reflect.run",
  "forge.read",
  "forge.run",
  "forge.export",
  "brain.read",
  "brain.write",
  "webhook.manage",
  "admin.users",
  "admin.keys",
  "admin.grants",
  "admin.audit",
  "system.admin",
];

const ROLES = ["admin", "operator", "viewer", "service", "owner"];

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/admin-control${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || "Admin request failed");
  return data as T;
}

function ShortId({ value }: { value: string | null | undefined }) {
  return (
    <span className="font-mono text-xs text-muted-foreground">
      {value ? value.slice(0, 8) : "none"}
    </span>
  );
}

export function AdminAccessConsole({ initialOrgs }: { initialOrgs: OrgResponse[] }) {
  const [orgs, setOrgs] = useState(initialOrgs);
  const [orgId, setOrgId] = useState(initialOrgs[0]?.id || "");
  const [principals, setPrincipals] = useState<PrincipalResponse[]>([]);
  const [keys, setKeys] = useState<ApiKeyResponse[]>([]);
  const [grants, setGrants] = useState<AccessGrantResponse[]>([]);
  const [audit, setAudit] = useState<AuditEventResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [rawKey, setRawKey] = useState<string | null>(null);
  const [resetTarget, setResetTarget] = useState<PrincipalResponse | null>(null);
  const [resetPasswordValue, setResetPasswordValue] = useState("");

  const org = useMemo(() => orgs.find((item) => item.id === orgId), [orgId, orgs]);
  const principalLabels = useMemo(
    () => new Map(principals.map((principal) => [principal.id, principal.display_name])),
    [principals]
  );

  const reload = useCallback(
    async (nextOrgId = orgId) => {
      if (!nextOrgId) return;
      const nextOrg = orgs.find((item) => item.id === nextOrgId);
      setLoading(true);
      try {
        const [nextPrincipals, nextKeys, nextGrants, nextAudit] = await Promise.all([
          api<PrincipalResponse[]>(`/principals?org_id=${nextOrgId}`),
          api<ApiKeyResponse[]>(
            `/api-keys?schema=${encodeURIComponent(nextOrg?.schema_name || "public")}`
          ),
          api<AccessGrantResponse[]>(`/access-grants?org_id=${nextOrgId}`),
          api<AuditEventResponse[]>(`/audit-events?org_id=${nextOrgId}&limit=50`),
        ]);
        setPrincipals(nextPrincipals);
        setKeys(
          nextKeys.filter(
            (key) => !key.principal_id || nextPrincipals.some((p) => p.id === key.principal_id)
          )
        );
        setGrants(nextGrants);
        setAudit(nextAudit);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Could not load access data");
      } finally {
        setLoading(false);
      }
    },
    [orgId, orgs]
  );

  useEffect(() => {
    reload().catch(() => null);
  }, [reload]);

  async function createOrg(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const created = await api<OrgResponse>("/orgs", {
        method: "POST",
        body: JSON.stringify({
          slug: form.get("slug"),
          name: form.get("name"),
          owner_email: form.get("owner_email"),
          owner_password: form.get("owner_password"),
          owner_name: form.get("owner_name"),
        }),
      });
      setOrgs((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      setOrgId(created.id);
      toast.success("Organization ready");
      event.currentTarget.reset();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not create org");
    }
  }

  async function createPrincipal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!orgId) {
      toast.error("Create an organization first");
      return;
    }
    const form = new FormData(event.currentTarget);
    try {
      await api<PrincipalResponse>("/principals", {
        method: "POST",
        body: JSON.stringify({
          org_id: orgId,
          email: form.get("email") || null,
          display_name: form.get("display_name"),
          principal_type: form.get("principal_type"),
          role: form.get("role"),
          password: form.get("password") || null,
        }),
      });
      toast.success("Principal created");
      event.currentTarget.reset();
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not create principal");
    }
  }

  async function createKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!org) {
      toast.error("Create an organization first");
      return;
    }
    const form = new FormData(event.currentTarget);
    const principalId = String(form.get("principal_id") || "");
    const principal = principals.find((item) => item.id === principalId);
    if (!principal) {
      toast.error("Select a principal for this key");
      return;
    }
    try {
      const created = await api<ApiKeyResponse>(
        `/api-keys?schema=${encodeURIComponent(org.schema_name)}`,
        {
          method: "POST",
          body: JSON.stringify({
            name: form.get("name"),
            role: principal?.role || "service",
            schema_name: org?.schema_name || "public",
            principal_id: principalId || null,
            description: form.get("description") || null,
            expires_days: Number(form.get("expires_days") || 90),
          }),
        }
      );
      setRawKey(created.raw_key || null);
      toast.success("Service key created");
      event.currentTarget.reset();
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not create key");
    }
  }

  async function createGrant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!orgId) {
      toast.error("Create an organization first");
      return;
    }
    const form = new FormData(event.currentTarget);
    const principalId = String(form.get("principal_id") || "");
    if (!principalId) {
      toast.error("Select a principal for this grant");
      return;
    }
    try {
      await api<AccessGrantResponse>("/access-grants", {
        method: "POST",
        body: JSON.stringify({
          org_id: orgId,
          subject_type: "principal",
          subject_id: principalId,
          action: form.get("action"),
          scope_type: form.get("scope_type"),
          scope_id: form.get("scope_id"),
        }),
      });
      toast.success("Grant added");
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not add grant");
    }
  }

  async function revokeKey(keyId: string) {
    try {
      await api(`/api-keys/${keyId}?schema=${encodeURIComponent(org?.schema_name || "public")}`, {
        method: "DELETE",
      });
      toast.success("Key revoked");
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not revoke key");
    }
  }

  async function updatePrincipal(principalId: string, params: { status?: string; role?: string }) {
    const query = new URLSearchParams();
    if (params.status) query.set("status", params.status);
    if (params.role) query.set("role", params.role);
    try {
      await api<PrincipalResponse>(`/principals/${principalId}?${query.toString()}`, {
        method: "PATCH",
      });
      toast.success("Principal updated");
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not update principal");
    }
  }

  async function resetPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!resetTarget) return;
    if (resetPasswordValue.length < 12) {
      toast.error("Password must be at least 12 characters");
      return;
    }
    try {
      await api(`/principals/${resetTarget.id}/password`, {
        method: "POST",
        body: JSON.stringify({ password: resetPasswordValue }),
      });
      toast.success("Password reset");
      setResetTarget(null);
      setResetPasswordValue("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not reset password");
    }
  }

  async function deleteGrant(grantId: string) {
    try {
      await api(`/access-grants/${grantId}`, { method: "DELETE" });
      toast.success("Grant removed");
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not remove grant");
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
        <div>
          <h1 className="text-xl font-semibold leading-tight">Access Control</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline">{org?.slug || "no org"}</Badge>
            <span className="font-mono">{org?.schema_name || "schema pending"}</span>
            <span>{principals.length} principals</span>
            <span>{keys.filter((key) => !key.revoked_at).length} active keys</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="h-9 rounded-md border bg-background px-3 text-sm"
            value={orgId}
            onChange={(event) => setOrgId(event.target.value)}
          >
            {orgs.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({item.slug})
              </option>
            ))}
          </select>
          <Button variant="outline" size="sm" onClick={() => reload()} disabled={loading}>
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>

      <Tabs defaultValue="overview">
        <TabsList className="h-auto w-full justify-start overflow-x-auto">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="keys">Keys</TabsTrigger>
          <TabsTrigger value="grants">Grants</TabsTrigger>
          <TabsTrigger value="roles">Roles</TabsTrigger>
          <TabsTrigger value="audit">Audit</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          {orgs.length === 0 && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-700 dark:text-amber-200">
              No organizations exist yet. Create the first organization and owner before user login
              can work.
            </div>
          )}
          <div className="grid gap-3 md:grid-cols-4">
            <Metric label="Org" value={org?.slug || "none"} />
            <Metric label="Schema" value={org?.schema_name || "none"} />
            <Metric label="Principals" value={String(principals.length)} />
            <Metric
              label="Active Keys"
              value={String(keys.filter((key) => !key.revoked_at).length)}
            />
          </div>
          <form onSubmit={createOrg} className="grid gap-3 rounded-lg border p-4 md:grid-cols-2">
            <h2 className="md:col-span-2 text-sm font-semibold">Create organization</h2>
            <Field name="slug" label="Slug" required />
            <Field name="name" label="Name" required />
            <Field name="owner_email" label="Owner email" type="email" required />
            <Field name="owner_name" label="Owner name" />
            <Field name="owner_password" label="Owner password" type="password" required />
            <Button className="md:self-end">
              <Plus className="h-4 w-4" />
              Create org
            </Button>
          </form>
        </TabsContent>

        <TabsContent value="users" className="space-y-4">
          {resetTarget && (
            <form
              onSubmit={resetPassword}
              className="grid gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 md:grid-cols-[minmax(0,1fr)_auto_auto]"
            >
              <div className="min-w-0">
                <Label htmlFor="reset_password">
                  Reset password for {resetTarget.display_name}
                </Label>
                <Input
                  id="reset_password"
                  type="password"
                  value={resetPasswordValue}
                  onChange={(event) => setResetPasswordValue(event.target.value)}
                  className="mt-1.5 bg-background"
                  autoFocus
                  required
                />
              </div>
              <Button className="self-end">Update</Button>
              <Button
                type="button"
                variant="outline"
                className="self-end"
                onClick={() => {
                  setResetTarget(null);
                  setResetPasswordValue("");
                }}
              >
                Cancel
              </Button>
            </form>
          )}
          <form
            onSubmit={createPrincipal}
            className="grid gap-3 rounded-lg border p-4 md:grid-cols-3"
          >
            <h2 className="md:col-span-3 text-sm font-semibold">
              Create user or service principal
            </h2>
            <Field name="display_name" label="Name" required />
            <Field name="email" label="Email" type="email" />
            <Field name="password" label="Password" type="password" />
            <SelectField name="principal_type" label="Type" options={["user", "service"]} />
            <SelectField name="role" label="Role" options={ROLES} />
            <Button className="md:self-end">
              <UserPlus className="h-4 w-4" />
              Create principal
            </Button>
          </form>
          <DataTable
            rows={principals.map((p) => [
              p.display_name,
              p.email || "service",
              p.principal_type,
              p.role,
              p.status,
              <ShortId key={p.id} value={p.id} />,
              <div key={`${p.id}-actions`} className="flex flex-wrap gap-2">
                <select
                  className="h-8 rounded-md border bg-background px-2 text-xs"
                  value={p.role}
                  onChange={(event) => updatePrincipal(p.id, { role: event.target.value })}
                >
                  {ROLES.map((role) => (
                    <option key={role} value={role}>
                      {role}
                    </option>
                  ))}
                </select>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    updatePrincipal(p.id, { status: p.status === "active" ? "disabled" : "active" })
                  }
                >
                  {p.status === "active" ? "Disable" : "Activate"}
                </Button>
                {p.principal_type === "user" && (
                  <Button size="sm" variant="outline" onClick={() => setResetTarget(p)}>
                    Reset
                  </Button>
                )}
              </div>,
            ])}
            headers={["Name", "Email", "Type", "Role", "Status", "ID", "Actions"]}
          />
        </TabsContent>

        <TabsContent value="keys" className="space-y-4">
          {rawKey && (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-green-500/40 bg-green-500/5 p-3">
              <code className="min-w-0 truncate text-xs">{rawKey}</code>
              <Button
                size="sm"
                variant="outline"
                onClick={() => navigator.clipboard.writeText(rawKey)}
              >
                <Copy className="h-4 w-4" />
                Copy
              </Button>
            </div>
          )}
          <form onSubmit={createKey} className="grid gap-3 rounded-lg border p-4 md:grid-cols-3">
            <h2 className="md:col-span-3 text-sm font-semibold">Create service key</h2>
            <Field name="name" label="Name" required />
            <SelectField
              name="principal_id"
              label="Principal"
              options={principals.map((p) => p.id)}
              labels={principals.map((p) => p.display_name)}
              required
            />
            <Field name="expires_days" label="Expires days" type="number" defaultValue="90" />
            <Field name="description" label="Description" />
            <Button className="md:self-end">
              <KeyRound className="h-4 w-4" />
              Create key
            </Button>
          </form>
          <DataTable
            headers={["Name", "Prefix", "Principal", "Role", "Expires", "Status", ""]}
            rows={keys.map((key) => [
              key.name,
              key.key_prefix || <ShortId key={key.id} value={key.id} />,
              <ShortId key={`${key.id}-p`} value={key.principal_id} />,
              key.role,
              key.expires_at?.slice(0, 10) || "never",
              key.revoked_at ? "revoked" : "active",
              key.revoked_at ? null : (
                <Button key={key.id} size="sm" variant="outline" onClick={() => revokeKey(key.id)}>
                  Revoke
                </Button>
              ),
            ])}
          />
        </TabsContent>

        <TabsContent value="grants" className="space-y-4">
          <form onSubmit={createGrant} className="grid gap-3 rounded-lg border p-4 md:grid-cols-5">
            <h2 className="md:col-span-5 text-sm font-semibold">Add action grant</h2>
            <SelectField
              name="principal_id"
              label="Principal"
              options={principals.map((p) => p.id)}
              labels={principals.map((p) => p.display_name)}
              required
            />
            <SelectField name="action" label="Action" options={ACTIONS} />
            <SelectField name="scope_type" label="Scope" options={["bank", "org", "system"]} />
            <Field name="scope_id" label="Scope ID" placeholder="bank-id or *" required />
            <Button className="md:self-end">
              <ShieldCheck className="h-4 w-4" />
              Add grant
            </Button>
          </form>
          <DataTable
            headers={["Principal", "Subject ID", "Action", "Scope", "Grant ID", ""]}
            rows={grants.map((g) => [
              principalLabels.get(g.subject_id) || <ShortId key={g.id} value={g.subject_id} />,
              <ShortId key={g.id} value={g.subject_id} />,
              g.action,
              `${g.scope_type}:${g.scope_id}`,
              <ShortId key={`${g.id}-grant`} value={g.id} />,
              <Button
                key={`${g.id}-delete`}
                size="sm"
                variant="outline"
                onClick={() => deleteGrant(g.id)}
              >
                <Trash2 className="h-4 w-4" />
                Remove
              </Button>,
            ])}
          />
        </TabsContent>

        <TabsContent value="roles">
          <div className="grid gap-3 md:grid-cols-2">
            {ROLES.map((role) => (
              <div key={role} className="rounded-lg border p-4">
                <div className="mb-2 flex items-center justify-between">
                  <h2 className="font-semibold capitalize">{role}</h2>
                  <Badge variant="outline">seeded</Badge>
                </div>
                <p className="text-sm text-muted-foreground">
                  {role === "owner" || role === "admin"
                    ? "Org-wide administration and all bank actions."
                    : role === "operator"
                      ? "Read, write, run, forge, and webhook actions on granted banks."
                      : role === "viewer"
                        ? "Read, recall, reflect, forge read, and brain read on granted banks."
                        : "Only explicitly granted actions."}
                </p>
              </div>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="audit">
          <DataTable
            headers={["Time", "Action", "Result", "Actor", "Target"]}
            rows={audit.map((event) => [
              event.created_at.slice(0, 19),
              event.action,
              event.result,
              <ShortId key={event.id} value={event.actor_principal_id} />,
              `${event.target_type || "none"}:${event.target_id || "none"}`,
            ])}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-2 truncate font-mono text-lg font-semibold">{value}</p>
    </div>
  );
}

function Field(
  props: React.InputHTMLAttributes<HTMLInputElement> & { label: string; name: string }
) {
  const { label, name, ...rest } = props;
  return (
    <div className="space-y-1.5">
      <Label htmlFor={name}>{label}</Label>
      <Input id={name} name={name} className="bg-secondary/60" {...rest} />
    </div>
  );
}

function SelectField({
  name,
  label,
  options,
  labels,
  required,
}: {
  name: string;
  label: string;
  options: string[];
  labels?: string[];
  required?: boolean;
}) {
  const empty = options.length === 0;
  return (
    <div className="space-y-1.5">
      <Label htmlFor={name}>{label}</Label>
      <select
        id={name}
        name={name}
        required={required}
        disabled={empty}
        className="h-9 w-full rounded-md border bg-secondary/60 px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60"
      >
        {empty && <option value="">No principals</option>}
        {options.map((option, index) => (
          <option key={option} value={option}>
            {labels?.[index] || option}
          </option>
        ))}
      </select>
    </div>
  );
}

function DataTable({ headers, rows }: { headers: string[]; rows: Array<Array<React.ReactNode>> }) {
  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className="min-w-[760px] w-full text-sm">
        <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            {headers.map((header) => (
              <th key={header} className="px-3 py-2 text-left font-medium">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.length === 0 ? (
            <tr>
              <td className="px-3 py-6 text-center text-muted-foreground" colSpan={headers.length}>
                No rows yet.
              </td>
            </tr>
          ) : (
            rows.map((row, index) => (
              <tr key={index} className="hover:bg-muted/20">
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} className="px-3 py-2 align-top">
                    {cell}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
