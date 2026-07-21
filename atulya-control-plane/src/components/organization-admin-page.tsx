"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  Clipboard,
  KeyRound,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Trash2,
  UserPlus,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Section = "overview" | "members" | "service-accounts" | "roles" | "access" | "audit";
type Identity = {
  active_org_id: string | null;
  org_name?: string | null;
  org_slug?: string | null;
  role: string;
};
type Role = {
  id: string;
  name: string;
  description: string | null;
  is_builtin: boolean;
  actions: string[];
};
type Member = {
  id: string;
  principal_id: string;
  email: string;
  display_name: string;
  role_id: string;
  role: string;
  status: string;
  bank_ids: string[];
  org_wide: boolean;
};
type ServiceAccount = {
  id: string;
  display_name: string;
  status: string;
  membership_id: string;
  role_id: string;
  role: string;
  active_keys: number;
  bank_ids: string[];
  org_wide: boolean;
};
type Invitation = {
  id: string;
  email: string;
  role_id: string;
  role: string | null;
  created_at: string;
  expires_at: string;
  status: string;
};
type ServiceKey = {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  description: string | null;
};
type EffectiveAccess = {
  principal_id: string;
  role: string;
  allowed_actions: string[];
  action_scopes: Record<string, string[]>;
  sources: Record<string, string[]>;
};
type AccessMatrix = {
  actions: string[];
  banks: Array<{ bank_id: string; name: string }>;
  members: Member[];
  services: ServiceAccount[];
  roles: Role[];
  grants: Array<{
    id: string;
    subject_id: string;
    action: string;
    scope_type: string;
    scope_id: string;
  }>;
  effective: Record<string, EffectiveAccess>;
};

const ACTION_GROUPS = [
  ["Banks", ["bank.read", "bank.write", "bank.delete", "bank.config"]],
  ["Memory", ["memory.retain", "memory.recall", "memory.delete", "reflect.run"]],
  ["Forge and brain", ["forge.read", "forge.run", "forge.export", "brain.read", "brain.write"]],
  [
    "Administration",
    ["webhook.manage", "admin.users", "admin.keys", "admin.grants", "admin.audit"],
  ],
] as const;

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/org-control${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message || detail?.code || body?.error || `HTTP ${response.status}`;
    toast.error(message);
    throw new Error(message);
  }
  return body as T;
}

function PageHeader({
  title,
  description,
  onRefresh,
  action,
}: {
  title: string;
  description: string;
  onRefresh: () => void;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 border-b pb-5 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold">{title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="flex items-center gap-2">
        {action}
        <Button variant="outline" size="icon" onClick={onRefresh} title="Refresh">
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

function Status({ value }: { value: string }) {
  return <Badge variant={value === "active" ? "default" : "secondary"}>{value}</Badge>;
}

export function OrganizationAdminPage({ section }: { section: Section }) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [data, setData] = useState<any>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  const refresh = useCallback(() => setVersion((value) => value + 1), []);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    (async () => {
      const meResponse = await fetch("/api/auth/me", { cache: "no-store" });
      if (!meResponse.ok) throw new Error("Session expired");
      const me = (await meResponse.json()) as Identity;
      if (!me.active_org_id) throw new Error("Select a workspace to continue");
      const org = me.active_org_id;
      let next: any;
      if (section === "overview") next = await api(`/${org}`);
      if (section === "members") {
        const [members, invitations, roleRows, matrix] = await Promise.all([
          api<Member[]>(`/${org}/members`),
          api<Invitation[]>(`/${org}/invitations`),
          api<Role[]>(`/${org}/roles`),
          api<AccessMatrix>(`/${org}/access`),
        ]);
        next = { members, invitations, banks: matrix.banks };
        if (live) setRoles(roleRows);
      }
      if (section === "service-accounts") {
        const [services, roleRows, matrix] = await Promise.all([
          api<ServiceAccount[]>(`/${org}/service-accounts`),
          api<Role[]>(`/${org}/roles`),
          api<AccessMatrix>(`/${org}/access`),
        ]);
        const keys = Object.fromEntries(
          await Promise.all(
            services.map(async (service) => [
              service.id,
              await api<ServiceKey[]>(`/${org}/service-accounts/${service.id}/keys`),
            ])
          )
        );
        next = { services, keys, banks: matrix.banks };
        if (live) setRoles(roleRows);
      }
      if (section === "roles") next = await api<Role[]>(`/${org}/roles`);
      if (section === "access") next = await api<AccessMatrix>(`/${org}/access`);
      if (section === "audit") {
        const [rows, matrix] = await Promise.all([
          api<any[]>(`/${org}/audit-events`),
          api<AccessMatrix>(`/${org}/access`),
        ]);
        next = { rows, actors: [...matrix.members, ...matrix.services] };
      }
      if (live) {
        setIdentity(me);
        setData(next);
      }
    })()
      .catch(
        (reason) => live && setError(reason instanceof Error ? reason.message : "Request failed")
      )
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [section, version]);

  if (loading)
    return (
      <div className="flex min-h-72 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  if (error)
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/5 p-5">
        <p className="font-medium">Unable to load administration</p>
        <p className="mt-1 text-sm text-muted-foreground">{error}</p>
        <Button className="mt-4" variant="outline" onClick={refresh}>
          Try again
        </Button>
      </div>
    );
  if (!identity?.active_org_id) return null;

  const orgId = identity.active_org_id;
  if (section === "overview") return <Overview data={data} refresh={refresh} />;
  if (section === "members")
    return (
      <Members
        orgId={orgId}
        data={data}
        roles={roles}
        currentRole={identity.role}
        refresh={refresh}
      />
    );
  if (section === "service-accounts")
    return <Services orgId={orgId} data={data} roles={roles} refresh={refresh} />;
  if (section === "roles") return <Roles orgId={orgId} roles={data} refresh={refresh} />;
  if (section === "access") return <Access orgId={orgId} data={data} refresh={refresh} />;
  return <Audit orgId={orgId} initial={data.rows} actors={data.actors} refresh={refresh} />;
}

function Overview({ data, refresh }: { data: any; refresh: () => void }) {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Workspace overview"
        description="Membership, services, and memory-bank coverage."
        onRefresh={refresh}
      />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Members", data.members],
          ["Service accounts", data.services],
          ["Roles", data.roles],
          ["Memory banks", data.banks],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-md border bg-card p-4">
            <p className="text-xs font-medium text-muted-foreground">{label}</p>
            <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
          </div>
        ))}
      </div>
      <div className="rounded-md border">
        <dl className="grid gap-px bg-border sm:grid-cols-2">
          {[
            ["Workspace", data.name],
            ["Slug", data.slug],
            ["Schema", data.schema_name],
            ["Status", data.status],
          ].map(([label, value]) => (
            <div key={label} className="bg-background px-4 py-3">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="mt-1 text-sm font-medium">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}

function Members({
  orgId,
  data,
  roles,
  currentRole,
  refresh,
}: {
  orgId: string;
  data: {
    members: Member[];
    invitations: Invitation[];
    banks: Array<{ bank_id: string; name: string }>;
  };
  roles: Role[];
  currentRole: string;
  refresh: () => void;
}) {
  const [open, setOpen] = useState(false);
  const submitInvite = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await api(`/${orgId}/invitations`, {
      method: "POST",
      body: JSON.stringify({
        email: form.get("email"),
        role_id: form.get("role_id"),
        bank_ids: form.getAll("bank_ids"),
      }),
    });
    toast.success("Invitation sent");
    setOpen(false);
    refresh();
  };
  return (
    <div className="space-y-5">
      <PageHeader
        title="Members"
        description="Invite people and control their role and bank scope."
        onRefresh={refresh}
        action={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button>
                <UserPlus className="mr-2 h-4 w-4" />
                Invite member
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Invite member</DialogTitle>
              </DialogHeader>
              <form className="space-y-4" onSubmit={(event) => void submitInvite(event)}>
                <div>
                  <Label htmlFor="invite-email">Email</Label>
                  <Input id="invite-email" name="email" type="email" required className="mt-1.5" />
                </div>
                <div>
                  <Label htmlFor="invite-role">Role</Label>
                  <select
                    id="invite-role"
                    name="role_id"
                    required
                    className="mt-1.5 h-10 w-full rounded-md border bg-background px-3 text-sm"
                  >
                    {roles
                      .filter((role) => role.name !== "owner" || currentRole === "owner")
                      .map((role) => (
                        <option key={role.id} value={role.id}>
                          {role.name}
                        </option>
                      ))}
                  </select>
                </div>
                <BankChecks banks={data.banks} />
                <Button className="w-full" type="submit">
                  Send invitation
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        }
      />
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Member</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Scope</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.members.map((member) => (
              <tr key={member.id} className="border-t">
                <td className="px-4 py-3">
                  <p className="font-medium">{member.display_name}</p>
                  <p className="text-xs text-muted-foreground">{member.email}</p>
                </td>
                <td className="px-4 py-3 capitalize">{member.role}</td>
                <td className="px-4 py-3">
                  {member.org_wide
                    ? "All banks"
                    : member.bank_ids.length
                      ? `${member.bank_ids.length} assigned`
                      : "No banks"}
                </td>
                <td className="px-4 py-3">
                  <Status value={member.status} />
                </td>
                <td className="px-4 py-3 text-right">
                  <EditMemberDialog
                    orgId={orgId}
                    member={member}
                    roles={roles}
                    currentRole={currentRole}
                    banks={data.banks}
                    refresh={refresh}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.members.length === 0 && (
          <p className="p-8 text-center text-sm text-muted-foreground">No members yet.</p>
        )}
      </div>
      <div>
        <h2 className="mb-2 text-sm font-semibold">Invitations</h2>
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Expires</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.invitations.map((invitation) => (
                <tr key={invitation.id} className="border-t">
                  <td className="px-4 py-3">{invitation.email}</td>
                  <td className="px-4 py-3 capitalize">{invitation.role || "Removed role"}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
                    {new Date(invitation.expires_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    <Status value={invitation.status} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    {invitation.status === "pending" && (
                      <Button
                        size="icon"
                        variant="ghost"
                        title="Revoke invitation"
                        onClick={async () => {
                          await api(`/${orgId}/invitations/${invitation.id}`, { method: "DELETE" });
                          toast.success("Invitation revoked");
                          refresh();
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.invitations.length === 0 && (
            <p className="p-6 text-center text-sm text-muted-foreground">No invitations.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function EditMemberDialog({
  orgId,
  member,
  roles,
  currentRole,
  banks,
  refresh,
}: {
  orgId: string;
  member: Member;
  roles: Role[];
  currentRole: string;
  banks: Array<{ bank_id: string; name: string }>;
  refresh: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [roleId, setRoleId] = useState(member.role_id);
  const [status, setStatus] = useState(member.status);
  const [bankIds, setBankIds] = useState(member.bank_ids);
  const roleName = roles.find((role) => role.id === roleId)?.name;
  const save = async () => {
    await api(`/${orgId}/members/${member.id}`, {
      method: "PATCH",
      body: JSON.stringify({ role_id: roleId, status, bank_ids: bankIds }),
    });
    toast.success("Member access updated");
    setOpen(false);
    refresh();
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="icon" variant="ghost" title="Edit member access">
          <Pencil className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit {member.display_name}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor={`member-role-${member.id}`}>Role</Label>
            <select
              id={`member-role-${member.id}`}
              value={roleId}
              onChange={(event) => setRoleId(event.target.value)}
              className="mt-1.5 h-10 w-full rounded-md border bg-background px-3 text-sm"
            >
              {roles
                .filter((role) => role.name !== "owner" || currentRole === "owner")
                .map((role) => (
                  <option key={role.id} value={role.id}>
                    {role.name}
                  </option>
                ))}
            </select>
          </div>
          <div>
            <Label htmlFor={`member-status-${member.id}`}>Status</Label>
            <select
              id={`member-status-${member.id}`}
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              className="mt-1.5 h-10 w-full rounded-md border bg-background px-3 text-sm"
            >
              <option value="active">Active</option>
              <option value="disabled">Disabled</option>
            </select>
          </div>
          {!["owner", "admin"].includes(roleName || "") && (
            <ControlledBankChecks banks={banks} selected={bankIds} onChange={setBankIds} />
          )}
          <Button className="w-full" onClick={() => void save()}>
            Save access
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function BankChecks({ banks }: { banks: Array<{ bank_id: string; name: string }> }) {
  if (!banks.length)
    return (
      <p className="text-sm text-muted-foreground">No memory banks are available to assign.</p>
    );
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-medium">Memory banks</legend>
      <div className="max-h-40 space-y-2 overflow-y-auto rounded-md border p-3">
        {banks.map((bank) => (
          <label key={bank.bank_id} className="flex items-center gap-2 text-sm">
            <Checkbox name="bank_ids" value={bank.bank_id} />
            {bank.name || bank.bank_id}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function ControlledBankChecks({
  banks,
  selected,
  onChange,
}: {
  banks: Array<{ bank_id: string; name: string }>;
  selected: string[];
  onChange: (bankIds: string[]) => void;
}) {
  if (!banks.length) {
    return <p className="text-sm text-muted-foreground">No memory banks are available.</p>;
  }
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-medium">Memory banks</legend>
      <div className="max-h-40 space-y-2 overflow-y-auto rounded-md border p-3">
        {banks.map((bank) => (
          <label key={bank.bank_id} className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={selected.includes(bank.bank_id)}
              onCheckedChange={(checked) =>
                onChange(
                  checked
                    ? [...selected, bank.bank_id]
                    : selected.filter((value) => value !== bank.bank_id)
                )
              }
            />
            {bank.name || bank.bank_id}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Services({
  orgId,
  data,
  roles,
  refresh,
}: {
  orgId: string;
  data: {
    services: ServiceAccount[];
    keys: Record<string, ServiceKey[]>;
    banks: Array<{ bank_id: string; name: string }>;
  };
  roles: Role[];
  refresh: () => void;
}) {
  const [secret, setSecret] = useState<string | null>(null);
  const createService = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await api(`/${orgId}/service-accounts`, {
      method: "POST",
      body: JSON.stringify({
        name: form.get("name"),
        role_id: form.get("role_id"),
        bank_ids: form.getAll("bank_ids"),
      }),
    });
    toast.success("Service account created");
    refresh();
  };
  return (
    <div className="space-y-5">
      <PageHeader
        title="Service accounts"
        description="Non-human identities with scoped, rotating API keys."
        onRefresh={refresh}
        action={
          <Dialog>
            <DialogTrigger asChild>
              <Button>
                <Plus className="mr-2 h-4 w-4" />
                New service
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create service account</DialogTitle>
              </DialogHeader>
              <form className="space-y-4" onSubmit={(event) => void createService(event)}>
                <div>
                  <Label htmlFor="service-name">Name</Label>
                  <Input id="service-name" name="name" required className="mt-1.5" />
                </div>
                <div>
                  <Label htmlFor="service-role">Role</Label>
                  <select
                    id="service-role"
                    name="role_id"
                    className="mt-1.5 h-10 w-full rounded-md border bg-background px-3 text-sm"
                  >
                    {roles
                      .filter((role) => !["owner", "admin"].includes(role.name))
                      .map((role) => (
                        <option key={role.id} value={role.id}>
                          {role.name}
                        </option>
                      ))}
                  </select>
                </div>
                <BankChecks banks={data.banks} />
                <Button className="w-full" type="submit">
                  Create service account
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        }
      />
      {secret && (
        <div className="flex items-center gap-3 rounded-md border border-primary/30 bg-primary/5 p-3">
          <KeyRound className="h-4 w-4 shrink-0" />
          <code className="min-w-0 flex-1 truncate text-xs">{secret}</code>
          <Button
            size="icon"
            variant="ghost"
            title="Copy key"
            onClick={() => {
              void navigator.clipboard.writeText(secret);
              toast.success("Key copied");
            }}
          >
            <Clipboard className="h-4 w-4" />
          </Button>
          <Button size="icon" variant="ghost" title="Dismiss" onClick={() => setSecret(null)}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      )}
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Service</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Active keys</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.services.map((service) => (
              <tr key={service.id} className="border-t">
                <td className="px-4 py-3 font-medium">{service.display_name}</td>
                <td className="px-4 py-3 capitalize">{service.role}</td>
                <td className="px-4 py-3 tabular-nums">{service.active_keys}</td>
                <td className="px-4 py-3 text-right">
                  <div className="flex justify-end gap-1">
                    <EditServiceDialog
                      orgId={orgId}
                      service={service}
                      roles={roles}
                      banks={data.banks}
                      refresh={refresh}
                    />
                    <ManageKeysDialog
                      orgId={orgId}
                      service={service}
                      keys={data.keys[service.id] || []}
                      reveal={setSecret}
                      refresh={refresh}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.services.length === 0 && (
          <p className="p-8 text-center text-sm text-muted-foreground">No service accounts yet.</p>
        )}
      </div>
    </div>
  );
}

function EditServiceDialog({
  orgId,
  service,
  roles,
  banks,
  refresh,
}: {
  orgId: string;
  service: ServiceAccount;
  roles: Role[];
  banks: Array<{ bank_id: string; name: string }>;
  refresh: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(service.display_name);
  const [roleId, setRoleId] = useState(service.role_id);
  const [status, setStatus] = useState(service.status);
  const [bankIds, setBankIds] = useState(service.bank_ids);
  const save = async () => {
    await api(`/${orgId}/service-accounts/${service.id}`, {
      method: "PATCH",
      body: JSON.stringify({ name, role_id: roleId, status, bank_ids: bankIds }),
    });
    toast.success("Service account updated");
    setOpen(false);
    refresh();
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="icon" variant="ghost" title="Edit service account">
          <Pencil className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit service account</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor={`service-edit-name-${service.id}`}>Name</Label>
            <Input
              id={`service-edit-name-${service.id}`}
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="mt-1.5"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label htmlFor={`service-edit-role-${service.id}`}>Role</Label>
              <select
                id={`service-edit-role-${service.id}`}
                value={roleId}
                onChange={(event) => setRoleId(event.target.value)}
                className="mt-1.5 h-10 w-full rounded-md border bg-background px-3 text-sm"
              >
                {roles
                  .filter((role) => !["owner", "admin", "operator", "viewer"].includes(role.name))
                  .map((role) => (
                    <option key={role.id} value={role.id}>
                      {role.name}
                    </option>
                  ))}
              </select>
            </div>
            <div>
              <Label htmlFor={`service-edit-status-${service.id}`}>Status</Label>
              <select
                id={`service-edit-status-${service.id}`}
                value={status}
                onChange={(event) => setStatus(event.target.value)}
                className="mt-1.5 h-10 w-full rounded-md border bg-background px-3 text-sm"
              >
                <option value="active">Active</option>
                <option value="disabled">Disabled</option>
              </select>
            </div>
          </div>
          <ControlledBankChecks banks={banks} selected={bankIds} onChange={setBankIds} />
          <Button className="w-full" onClick={() => void save()} disabled={!name.trim()}>
            Save service account
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ManageKeysDialog({
  orgId,
  service,
  keys,
  reveal,
  refresh,
}: {
  orgId: string;
  service: ServiceAccount;
  keys: ServiceKey[];
  reveal: (secret: string) => void;
  refresh: () => void;
}) {
  const create = async () => {
    const result = await api<{ raw_key: string }>(`/${orgId}/service-accounts/${service.id}/keys`, {
      method: "POST",
      body: JSON.stringify({ name: `${service.display_name} key`, expires_days: 90 }),
    });
    reveal(result.raw_key);
    toast.success("Key created. Copy it now.");
    refresh();
  };
  const rotate = async (key: ServiceKey) => {
    const result = await api<{ raw_key: string }>(
      `/${orgId}/service-accounts/${service.id}/keys/${key.id}/rotate?overlap_hours=24`,
      {
        method: "POST",
        body: JSON.stringify({ name: `${key.name} replacement`, expires_days: 90 }),
      }
    );
    reveal(result.raw_key);
    toast.success("Key rotated with a 24-hour overlap");
    refresh();
  };
  const revoke = async (key: ServiceKey) => {
    if (!window.confirm(`Revoke ${key.name}? This cannot be undone.`)) return;
    await api(`/${orgId}/service-accounts/${service.id}/keys/${key.id}`, { method: "DELETE" });
    toast.success("Key revoked");
    refresh();
  };
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <KeyRound className="mr-2 h-3.5 w-3.5" />
          Keys
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{service.display_name} keys</DialogTitle>
        </DialogHeader>
        <div className="flex justify-end">
          <Button size="sm" onClick={() => void create()} disabled={service.status !== "active"}>
            <Plus className="mr-2 h-4 w-4" />
            Create key
          </Button>
        </div>
        <div className="max-h-80 overflow-auto rounded-md border">
          <table className="w-full min-w-[620px] text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2">Key</th>
                <th className="px-3 py-2">Expires</th>
                <th className="px-3 py-2">Last used</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {keys.map((key) => (
                <tr key={key.id} className="border-t">
                  <td className="px-3 py-2">
                    <p className="font-medium">{key.name}</p>
                    <code className="text-[11px] text-muted-foreground">{key.key_prefix}...</code>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs">
                    {key.expires_at ? new Date(key.expires_at).toLocaleDateString() : "Never"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground">
                    {key.last_used_at ? new Date(key.last_used_at).toLocaleString() : "Never"}
                  </td>
                  <td className="px-3 py-2">
                    <Status value={key.revoked_at ? "revoked" : "active"} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    {!key.revoked_at && (
                      <div className="flex justify-end gap-1">
                        <Button
                          size="icon"
                          variant="ghost"
                          title="Rotate key"
                          onClick={() => void rotate(key)}
                        >
                          <RotateCcw className="h-4 w-4" />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          title="Revoke key"
                          onClick={() => void revoke(key)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {keys.length === 0 && (
            <p className="p-6 text-center text-sm text-muted-foreground">No keys created.</p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Roles({ orgId, roles, refresh }: { orgId: string; roles: Role[]; refresh: () => void }) {
  const [selected, setSelected] = useState<string[]>([]);
  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await api(`/${orgId}/roles`, {
      method: "POST",
      body: JSON.stringify({
        name: form.get("name"),
        description: form.get("description") || null,
        actions: selected,
      }),
    });
    toast.success("Role created");
    setSelected([]);
    refresh();
  };
  return (
    <div className="space-y-5">
      <PageHeader
        title="Roles"
        description="Built-in and custom action bundles. System access cannot be delegated here."
        onRefresh={refresh}
        action={
          <Dialog>
            <DialogTrigger asChild>
              <Button>
                <Plus className="mr-2 h-4 w-4" />
                Custom role
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-2xl">
              <DialogHeader>
                <DialogTitle>Create custom role</DialogTitle>
              </DialogHeader>
              <form className="space-y-4" onSubmit={(event) => void create(event)}>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <Label htmlFor="role-name">Role name</Label>
                    <Input
                      id="role-name"
                      name="name"
                      required
                      pattern="[a-z][a-z0-9_-]+"
                      className="mt-1.5"
                    />
                  </div>
                  <div>
                    <Label htmlFor="role-description">Description</Label>
                    <Input id="role-description" name="description" className="mt-1.5" />
                  </div>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  {ACTION_GROUPS.map(([group, actions]) => (
                    <fieldset key={group} className="rounded-md border p-3">
                      <legend className="px-1 text-sm font-medium">{group}</legend>
                      <div className="space-y-2">
                        {actions.map((action) => (
                          <label key={action} className="flex items-center gap-2 text-xs">
                            <Checkbox
                              checked={selected.includes(action)}
                              onCheckedChange={(checked) =>
                                setSelected((current) =>
                                  checked
                                    ? [...current, action]
                                    : current.filter((value) => value !== action)
                                )
                              }
                            />
                            {action}
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  ))}
                </div>
                <Button className="w-full" type="submit" disabled={!selected.length}>
                  Create role
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        }
      />
      <div className="grid gap-3 lg:grid-cols-2">
        {roles.map((role) => (
          <div key={role.id} className="rounded-md border p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium capitalize">{role.name}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {role.description || "Custom permission bundle"}
                </p>
              </div>
              <div className="flex items-center gap-1">
                {role.is_builtin ? (
                  <Badge variant="secondary">Built in</Badge>
                ) : (
                  <>
                    <EditRoleDialog orgId={orgId} role={role} refresh={refresh} />
                    <Button
                      size="icon"
                      variant="ghost"
                      title="Delete custom role"
                      onClick={async () => {
                        if (!window.confirm(`Delete role ${role.name}?`)) return;
                        await api(`/${orgId}/roles/${role.id}`, { method: "DELETE" });
                        toast.success("Role deleted");
                        refresh();
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </>
                )}
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-1.5">
              {role.actions.map((action) => (
                <Badge key={action} variant="outline" className="font-mono text-[10px]">
                  {action}
                </Badge>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EditRoleDialog({
  orgId,
  role,
  refresh,
}: {
  orgId: string;
  role: Role;
  refresh: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [description, setDescription] = useState(role.description || "");
  const [actions, setActions] = useState(role.actions);
  const save = async () => {
    await api(`/${orgId}/roles/${role.id}`, {
      method: "PATCH",
      body: JSON.stringify({ description: description || null, actions }),
    });
    toast.success("Role updated");
    setOpen(false);
    refresh();
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="icon" variant="ghost" title="Edit custom role">
          <Pencil className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit {role.name}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor={`role-edit-description-${role.id}`}>Description</Label>
            <Input
              id={`role-edit-description-${role.id}`}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="mt-1.5"
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {ACTION_GROUPS.map(([group, groupActions]) => (
              <fieldset key={group} className="rounded-md border p-3">
                <legend className="px-1 text-sm font-medium">{group}</legend>
                <div className="space-y-2">
                  {groupActions.map((action) => (
                    <label key={action} className="flex items-center gap-2 text-xs">
                      <Checkbox
                        checked={actions.includes(action)}
                        onCheckedChange={(checked) =>
                          setActions((current) =>
                            checked
                              ? [...current, action]
                              : current.filter((value) => value !== action)
                          )
                        }
                      />
                      {action}
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
          </div>
          <Button className="w-full" onClick={() => void save()}>
            Save role
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Access({
  orgId,
  data,
  refresh,
}: {
  orgId: string;
  data: AccessMatrix;
  refresh: () => void;
}) {
  const [action, setAction] = useState(data.actions[0] || "bank.read");
  const principals = useMemo(
    () => [
      ...data.members.map((item) => ({
        id: item.principal_id,
        name: item.display_name,
        role: item.role,
      })),
      ...data.services.map((item) => ({ id: item.id, name: item.display_name, role: item.role })),
    ],
    [data]
  );
  return (
    <div className="space-y-5">
      <PageHeader
        title="Effective access"
        description="Inspect effective permissions and manage additive exceptions."
        onRefresh={refresh}
        action={<GrantDialog orgId={orgId} data={data} principals={principals} refresh={refresh} />}
      />
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <Label htmlFor="access-action">Action</Label>
          <select
            id="access-action"
            value={action}
            onChange={(event) => setAction(event.target.value)}
            className="mt-1 h-9 min-w-60 rounded-md border bg-background px-3 text-sm"
          >
            {data.actions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
        <p className="text-xs text-muted-foreground">
          Checks include role scopes and direct grants.
        </p>
      </div>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="sticky left-0 bg-muted px-4 py-3">Identity</th>
              <th className="px-4 py-3">Role</th>
              {data.banks.map((bank) => (
                <th key={bank.bank_id} className="px-3 py-3 text-center">
                  {bank.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {principals.map((principal) => {
              const effective = data.effective[principal.id];
              const scopes = new Set(effective?.action_scopes[action] || []);
              return (
                <tr key={principal.id} className="border-t">
                  <td className="sticky left-0 bg-background px-4 py-3 font-medium">
                    {principal.name}
                  </td>
                  <td className="px-4 py-3 capitalize">{principal.role}</td>
                  {data.banks.map((bank) => {
                    const allowed = scopes.has("org:*") || scopes.has(`bank:${bank.bank_id}`);
                    return (
                      <td key={bank.bank_id} className="px-3 py-3 text-center">
                        {allowed ? (
                          <Check className="mx-auto h-4 w-4 text-primary" />
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
        {principals.length === 0 && (
          <p className="p-8 text-center text-sm text-muted-foreground">No identities to display.</p>
        )}
      </div>
      <div>
        <h2 className="mb-2 text-sm font-semibold">Direct grants</h2>
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Identity</th>
                <th className="px-4 py-3">Action</th>
                <th className="px-4 py-3">Scope</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.grants.map((grant) => (
                <tr key={grant.id} className="border-t">
                  <td className="px-4 py-3">
                    {principals.find((principal) => principal.id === grant.subject_id)?.name ||
                      grant.subject_id}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">{grant.action}</td>
                  <td className="px-4 py-3 font-mono text-xs">
                    {grant.scope_type}:{grant.scope_id}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      size="icon"
                      variant="ghost"
                      title="Remove direct grant"
                      onClick={async () => {
                        await api(`/${orgId}/grants/${grant.id}`, { method: "DELETE" });
                        toast.success("Grant removed");
                        refresh();
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.grants.length === 0 && (
            <p className="p-6 text-center text-sm text-muted-foreground">No direct grants.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function GrantDialog({
  orgId,
  data,
  principals,
  refresh,
}: {
  orgId: string;
  data: AccessMatrix;
  principals: Array<{ id: string; name: string; role: string }>;
  refresh: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [principalId, setPrincipalId] = useState(principals[0]?.id || "");
  const [action, setAction] = useState(data.actions[0] || "bank.read");
  const [scope, setScope] = useState("org:*");
  const create = async () => {
    const [scopeType, scopeId] = scope.split(":", 2);
    await api(`/${orgId}/grants`, {
      method: "POST",
      body: JSON.stringify({
        principal_id: principalId,
        action,
        scope_type: scopeType,
        scope_id: scopeId,
      }),
    });
    toast.success("Direct grant added");
    setOpen(false);
    refresh();
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button disabled={!principals.length}>
          <Plus className="mr-2 h-4 w-4" />
          Add grant
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add direct grant</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor="grant-principal">Identity</Label>
            <select
              id="grant-principal"
              value={principalId}
              onChange={(event) => setPrincipalId(event.target.value)}
              className="mt-1.5 h-10 w-full rounded-md border bg-background px-3 text-sm"
            >
              {principals.map((principal) => (
                <option key={principal.id} value={principal.id}>
                  {principal.name} ({principal.role})
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="grant-action">Action</Label>
            <select
              id="grant-action"
              value={action}
              onChange={(event) => setAction(event.target.value)}
              className="mt-1.5 h-10 w-full rounded-md border bg-background px-3 font-mono text-sm"
            >
              {data.actions.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="grant-scope">Scope</Label>
            <select
              id="grant-scope"
              value={scope}
              onChange={(event) => setScope(event.target.value)}
              className="mt-1.5 h-10 w-full rounded-md border bg-background px-3 text-sm"
            >
              <option value="org:*">All memory banks</option>
              {data.banks.map((bank) => (
                <option key={bank.bank_id} value={`bank:${bank.bank_id}`}>
                  {bank.name || bank.bank_id}
                </option>
              ))}
            </select>
          </div>
          <Button className="w-full" onClick={() => void create()} disabled={!principalId}>
            Add grant
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Audit({
  orgId,
  initial,
  actors,
  refresh,
}: {
  orgId: string;
  initial: any[];
  actors: Array<Member | ServiceAccount>;
  refresh: () => void;
}) {
  const [rows, setRows] = useState(initial);
  const filter = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const query = new URLSearchParams();
    for (const name of ["actor_id", "action", "result", "target"]) {
      const value = String(form.get(name) || "");
      if (value) query.set(name, value);
    }
    setRows(await api(`/${orgId}/audit-events?${query}`));
  };
  return (
    <div className="space-y-5">
      <PageHeader
        title="Audit log"
        description="Immutable actor, action, target, and result history."
        onRefresh={refresh}
      />
      <form
        className="flex flex-wrap items-end gap-2 rounded-md border p-3"
        onSubmit={(event) => void filter(event)}
      >
        <div className="min-w-48 flex-1">
          <Label htmlFor="audit-actor">Actor</Label>
          <select
            id="audit-actor"
            name="actor_id"
            className="mt-1 h-10 w-full rounded-md border bg-background px-3 text-sm"
          >
            <option value="">All actors</option>
            {actors.map((actor) => {
              const id = "principal_id" in actor ? actor.principal_id : actor.id;
              return (
                <option key={id} value={id}>
                  {actor.display_name}
                </option>
              );
            })}
          </select>
        </div>
        <div className="min-w-48 flex-1">
          <Label htmlFor="audit-action">Action</Label>
          <Input id="audit-action" name="action" placeholder="admin.keys.create" className="mt-1" />
        </div>
        <div>
          <Label htmlFor="audit-result">Result</Label>
          <select
            id="audit-result"
            name="result"
            className="mt-1 h-10 rounded-md border bg-background px-3 text-sm"
          >
            <option value="">All results</option>
            <option value="success">Success</option>
            <option value="denied">Denied</option>
          </select>
        </div>
        <div className="min-w-40 flex-1">
          <Label htmlFor="audit-target">Target ID</Label>
          <Input id="audit-target" name="target" className="mt-1" />
        </div>
        <Button type="submit">Filter</Button>
      </form>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[760px] text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Time</th>
              <th className="px-4 py-3">Actor</th>
              <th className="px-4 py-3">Action</th>
              <th className="px-4 py-3">Target</th>
              <th className="px-4 py-3">Result</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t">
                <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
                  {new Date(row.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-3">{row.actor_name || "System"}</td>
                <td className="px-4 py-3 font-mono text-xs">{row.action}</td>
                <td className="max-w-56 truncate px-4 py-3 text-xs">{row.target_id || "-"}</td>
                <td className="px-4 py-3">
                  <Status value={row.result} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && (
          <p className="p-8 text-center text-sm text-muted-foreground">No matching events.</p>
        )}
      </div>
    </div>
  );
}
