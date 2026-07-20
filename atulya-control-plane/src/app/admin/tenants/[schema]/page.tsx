/**
 * Admin › Tenants › [schema] › Banks
 *
 */

import Link from "next/link";
import { PlatformAdminRequired } from "@/components/platform-admin-required";
import { adminFetch } from "@/lib/admin-api";
import { canUsePlatformAdmin, getCurrentIdentity } from "@/lib/server-auth";

interface BankRow {
  bank_id: string;
  name: string | null;
  created_at: string;
  updated_at: string;
}

export default async function AdminTenantBanksPage({
  params,
}: {
  params: Promise<{ schema: string }>;
}) {
  const identity = await getCurrentIdentity();
  if (!canUsePlatformAdmin(identity)) return <PlatformAdminRequired />;

  const { schema } = await params;
  let banks: BankRow[] = [];
  let error: string | null = null;

  try {
    banks = await adminFetch<BankRow[]>(`/tenants/${schema}/banks`);
  } catch (e) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  return (
    <div>
      <div className="mb-6 flex items-center gap-3">
        <Link href="/admin/tenants" className="text-muted-foreground hover:text-foreground text-sm">
          ← Tenants
        </Link>
        <h1 className="text-xl font-semibold">
          Banks in schema: <code className="font-mono">{schema}</code>
        </h1>
      </div>

      {error && <p className="text-destructive mb-4">[error] {error}</p>}

      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="pb-2 pr-4 font-medium">Bank ID</th>
            <th className="pb-2 pr-4 font-medium">Name</th>
            <th className="pb-2 font-medium">Created</th>
          </tr>
        </thead>
        <tbody>
          {banks.map((b) => (
            <tr key={b.bank_id} className="border-b hover:bg-muted/30">
              <td className="py-2 pr-4 font-mono text-xs">{b.bank_id}</td>
              <td className="py-2 pr-4">
                {b.name ?? <span className="text-muted-foreground">—</span>}
              </td>
              <td className="py-2 text-muted-foreground text-xs">{b.created_at?.slice(0, 19)}</td>
            </tr>
          ))}
          {banks.length === 0 && !error && (
            <tr>
              <td colSpan={3} className="py-4 text-muted-foreground text-center">
                No banks in this schema.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
