"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, Loader2, LockKeyhole } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function AuthCompletionPanel({ mode }: { mode: "verify" | "reset" | "invite" | "forgot" }) {
  const search = useSearchParams();
  const router = useRouter();
  const token = search.get("token") || "";
  const [state, setState] = useState<"form" | "loading" | "done" | "error">(
    mode === "verify" ? "loading" : "form"
  );
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (mode !== "verify") return;
    if (!token) {
      setState("error");
      setMessage("Verification token is missing.");
      return;
    }
    fetch("/api/auth/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body?.detail?.code || "Verification failed");
        }
        router.replace("/dashboard");
        router.refresh();
      })
      .catch((reason) => {
        setMessage(reason instanceof Error ? reason.message : "Verification failed");
        setState("error");
      });
  }, [mode, router, token]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setState("loading");
    setMessage("");
    const form = new FormData(event.currentTarget);
    const path =
      mode === "forgot"
        ? "/api/auth/forgot-password"
        : mode === "reset"
          ? "/api/auth/reset-password"
          : "/api/auth/accept-invitation";
    const payload =
      mode === "forgot"
        ? { email: form.get("email") }
        : mode === "reset"
          ? { token, password: form.get("password") }
          : {
              token,
              display_name: form.get("name") || null,
              password: form.get("password") || null,
            };
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setMessage(body?.detail?.code || body?.detail || "Request failed");
      setState("error");
      return;
    }
    setState("done");
  };

  const title =
    mode === "verify"
      ? "Verifying account"
      : mode === "forgot"
        ? "Reset your password"
        : mode === "reset"
          ? "Choose a new password"
          : "Accept invitation";
  if (state === "loading")
    return (
      <Shell title={title}>
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Please wait...
        </div>
      </Shell>
    );
  if (state === "done")
    return (
      <Shell title="Request complete">
        <div className="flex gap-3">
          <CheckCircle2 className="h-5 w-5 text-primary" />
          <p className="text-sm text-muted-foreground">
            {mode === "forgot"
              ? "If that account exists, a reset link has been sent."
              : "You can now sign in with your account."}
          </p>
        </div>
        <Button asChild className="mt-5 w-full">
          <Link href="/login">Continue to sign in</Link>
        </Button>
      </Shell>
    );
  if (mode === "verify")
    return (
      <Shell title="Verification failed">
        <p className="text-sm text-destructive">{message}</p>
        <Button asChild variant="outline" className="mt-5 w-full">
          <Link href="/login">Back to sign in</Link>
        </Button>
      </Shell>
    );

  return (
    <Shell title={title}>
      <form className="space-y-4" onSubmit={(event) => void submit(event)}>
        {mode === "forgot" && (
          <div>
            <Label htmlFor="recovery-email">Email</Label>
            <Input id="recovery-email" name="email" type="email" required className="mt-1.5" />
          </div>
        )}
        {mode === "invite" && (
          <div>
            <Label htmlFor="invite-name">Full name for new accounts</Label>
            <Input id="invite-name" name="name" className="mt-1.5" />
          </div>
        )}
        {mode !== "forgot" && (
          <div>
            <Label htmlFor="new-password">Password for new accounts</Label>
            <Input
              id="new-password"
              name="password"
              type="password"
              minLength={12}
              className="mt-1.5"
            />
          </div>
        )}
        {state === "error" && <p className="text-sm text-destructive">{message}</p>}
        <Button type="submit" className="w-full">
          Continue
        </Button>
      </form>
    </Shell>
  );
}

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border bg-card p-6 shadow-sm">
      <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary">
        <LockKeyhole className="h-5 w-5 text-primary-foreground" />
      </div>
      <h1 className="mb-5 mt-4 text-xl font-semibold">{title}</h1>
      {children}
    </div>
  );
}
