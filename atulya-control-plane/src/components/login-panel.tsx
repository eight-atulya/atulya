"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { LockKeyhole, Loader2, UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type AuthMode = "login" | "signup";

interface SignupState {
  mode: string;
  available: boolean;
  org_count: number;
}

export function LoginPanel() {
  const router = useRouter();
  const search = useSearchParams();
  const [mode, setMode] = useState<AuthMode>("login");
  const [signupState, setSignupState] = useState<SignupState | null>(null);
  const [workspaceName, setWorkspaceName] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const requestedPath = search.get("next") || "/dashboard";
  const nextPath =
    requestedPath.startsWith("/") &&
    !requestedPath.startsWith("//") &&
    !requestedPath.startsWith("/admin")
      ? requestedPath
      : "/dashboard";
  const workspaceSlug = useMemo(() => slugify(workspaceName), [workspaceName]);
  const signupAvailable = Boolean(signupState?.available);
  const submitDisabled = loading || (mode === "signup" && !workspaceSlug);

  useEffect(() => {
    fetch("/api/auth/signup-state")
      .then((res) => (res.ok ? res.json() : null))
      .then((data: SignupState | null) => setSignupState(data))
      .catch(() => setSignupState(null));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(mode === "signup" ? "/api/auth/signup" : "/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          mode === "signup"
            ? {
                org_slug: workspaceSlug,
                org_name: workspaceName.trim(),
                owner_name: name.trim() || null,
                owner_email: email.trim(),
                owner_password: password,
              }
            : { email: email.trim(), password }
        ),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || body.error || "Authentication failed");
      }
      router.replace(nextPath);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not sign in");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={submit} className="max-w-xl rounded-lg border bg-card p-5 shadow-sm">
      <div className="mb-5 flex items-center gap-3 border-b pb-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary">
          {mode === "signup" ? (
            <UserPlus className="h-5 w-5 text-primary-foreground" />
          ) : (
            <LockKeyhole className="h-5 w-5 text-primary-foreground" />
          )}
        </div>
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold leading-tight">
            {mode === "signup" ? "Create workspace" : "Sign in"}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {mode === "signup" ? "Set up the first owner account." : "Access your memory banks."}
          </p>
        </div>
      </div>

      <div className="grid gap-4">
        {mode === "signup" && (
          <>
            <Field
              id="workspace"
              label="Workspace name"
              value={workspaceName}
              onChange={setWorkspaceName}
              autoComplete="organization"
              placeholder="Acme Research"
            />
            <Field
              id="name"
              label="Full name"
              value={name}
              onChange={setName}
              autoComplete="name"
              placeholder="Ada Lovelace"
            />
          </>
        )}
        <Field
          id="email"
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
          placeholder="name@company.com"
        />
        <Field
          id="password"
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
          placeholder="Enter password"
          minLength={mode === "signup" ? 12 : undefined}
        />
      </div>

      {mode === "signup" && workspaceName && (
        <p className="mt-3 text-xs text-muted-foreground">
          Workspace slug: <span className="font-mono">{workspaceSlug || "workspace"}</span>
        </p>
      )}

      {error && (
        <div className="mt-4 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <Button type="submit" className="mt-5 w-full" disabled={submitDisabled}>
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : mode === "signup" ? (
          <UserPlus className="h-4 w-4" />
        ) : (
          <LockKeyhole className="h-4 w-4" />
        )}
        {mode === "signup" ? "Create workspace" : "Sign in"}
      </Button>

      {signupAvailable && (
        <div className="mt-4 border-t pt-4 text-center text-sm text-muted-foreground">
          {mode === "login" ? (
            <button
              type="button"
              className="font-medium text-foreground underline-offset-4 hover:underline"
              onClick={() => {
                setError(null);
                setMode("signup");
              }}
            >
              Create the first workspace
            </button>
          ) : (
            <button
              type="button"
              className="font-medium text-foreground underline-offset-4 hover:underline"
              onClick={() => {
                setError(null);
                setMode("login");
              }}
            >
              Back to sign in
            </button>
          )}
        </div>
      )}
    </form>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  type = "text",
  autoComplete,
  placeholder,
  minLength,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  autoComplete?: string;
  placeholder?: string;
  minLength?: number;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete={autoComplete}
        placeholder={placeholder}
        minLength={minLength}
        required
        className="h-11 bg-secondary/60"
      />
    </div>
  );
}

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}
