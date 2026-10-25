"use client";

import { Building2, Store } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Logo } from "@/components/marketing/chrome";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect, Stepper } from "@/components/ui/core";
import { ApiError, http } from "@/lib/api";
import { cn } from "@/lib/utils";

const KINDS = [
  { key: "business", icon: Store, title: "Business or SaaS", body: "Manage your own websites." },
  { key: "agency", icon: Building2, title: "Agency", body: "Manage client sites in separate workspaces with branded reports." },
] as const;

export default function Onboarding() {
  const router = useRouter();
  const [kind, setKind] = React.useState<"business" | "agency">("business");
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const tz = typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : "UTC";
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setLoading(true);
    try {
      await http("/organizations", { json: { name: f.get("name"), kind, locale: f.get("locale"), timezone: f.get("timezone") } });
      router.push(kind === "agency" ? "/app/workspaces?welcome=1" : "/app/sites/new");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the organization.");
      setLoading(false);
    }
  }
  return (
    <main id="main" className="mx-auto max-w-2xl px-4 py-12">
      <Logo />
      <div className="mt-8">
        <Stepper steps={["Account", "Organization", "First website"]} current={1} />
      </div>
      <h1 className="mt-8 font-display text-4xl tracking-tight">Set up your organization</h1>
      <form onSubmit={submit} className="mt-8 space-y-6">
        <fieldset>
          <legend className="mb-2 text-[13px] font-medium">Organization type</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            {KINDS.map((k) => (
              <label key={k.key} className={cn("flex cursor-pointer gap-3 rounded-xl border bg-surface p-4 transition-colors", kind === k.key ? "border-accent ring-1 ring-accent/30" : "border-border hover:border-border-strong")}>
                <input type="radio" name="kind" value={k.key} checked={kind === k.key} onChange={() => setKind(k.key)} className="sr-only" />
                <k.icon className="mt-0.5 size-5 text-accent" aria-hidden />
                <span>
                  <span className="block font-medium">{k.title}</span>
                  <span className="text-[13px] text-fg-muted">{k.body}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <Field label="Organization name" htmlFor="name">
          <Input id="name" name="name" required maxLength={200} placeholder="Northwind Coffee" />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Locale" htmlFor="locale">
            <NativeSelect id="locale" name="locale" defaultValue="en-US" className="w-full">
              {["en-US", "en-GB", "de-DE", "fr-FR", "es-ES", "pt-BR", "ja-JP", "en-IN"].map((l) => <option key={l}>{l}</option>)}
            </NativeSelect>
          </Field>
          <Field label="Time zone" htmlFor="timezone">
            <Input id="timezone" name="timezone" defaultValue={tz} />
          </Field>
        </div>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <Button type="submit" size="lg" loading={loading}>Continue</Button>
      </form>
    </main>
  );
}
