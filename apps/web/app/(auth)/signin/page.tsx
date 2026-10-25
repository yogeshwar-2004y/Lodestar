"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Alert, Field, Input } from "@/components/ui/core";
import { ApiError, http } from "@/lib/api";
import { useMeta } from "@/lib/hooks";

export default function SignIn() {
  const router = useRouter();
  const meta = useMeta();
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setLoading(true);
    setError(null);
    try {
      const s = await http<{ organization: unknown }>("/auth/login", { json: { email: f.get("email"), password: f.get("password") } });
      router.push(s.organization ? "/app" : "/onboarding");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed.");
    } finally {
      setLoading(false);
    }
  }
  return (
    <>
      <h1 className="text-xl font-semibold">Welcome back</h1>
      <p className="mt-1 text-sm text-fg-muted">Sign in to your workspace.</p>
      {meta.data?.demo_mode && (
        <Alert tone="info" className="mt-5" title="Demo mode">
          Use <code>demo@lodestar.example</code> / <code>demo-password-123</code> after running <code>make seed</code>.
        </Alert>
      )}
      <form onSubmit={submit} className="mt-6 space-y-4">
        <Field label="Email" htmlFor="email">
          <Input id="email" name="email" type="email" autoComplete="email" required />
        </Field>
        <Field label="Password" htmlFor="password">
          <Input id="password" name="password" type="password" autoComplete="current-password" required />
        </Field>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <Button type="submit" className="w-full" loading={loading}>
          Sign in
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-fg-muted">
        New here? <Link href="/signup" className="text-accent hover:underline">Create an account</Link>
      </p>
    </>
  );
}
