"use client";

import { useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Alert, Skeleton } from "@/components/ui/core";
import { http } from "@/lib/api";
import { fmtNumber } from "@/lib/utils";

type Plan = { key: string; name: string; monthly_price_cents: number; currency: string; included_credits: number; max_sites: number; max_pages_per_crawl: number; max_workspaces: number; features: string[] };

export default function Pricing() {
  const { data, isLoading, error } = useQuery({ queryKey: ["plans"], queryFn: () => http<Plan[]>("/billing/plans") });
  return (
    <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
      <h1 className="font-display text-5xl tracking-tight">Pricing</h1>
      <p className="mt-3 max-w-2xl text-fg-muted">
        A subscription for the sites you manage, plus AI credits for crawling and agent work. Credits are metered in a transparent ledger;
        you can see every charge.
      </p>
      {error && <Alert tone="danger" className="mt-8" title="Plans are unavailable right now">Please try again shortly.</Alert>}
      <div className="mt-10 grid gap-5 md:grid-cols-3">
        {isLoading && [0, 1, 2].map((i) => <Skeleton key={i} className="h-96 rounded-2xl" />)}
        {data?.map((p, i) => (
          <div key={p.key} className={`relative flex flex-col rounded-2xl border bg-surface p-6 shadow-card ${i === 1 ? "border-accent ring-1 ring-accent/30" : "border-border"}`}>
            {i === 1 && <span className="absolute -top-3 left-6 rounded-full bg-accent px-2.5 py-0.5 text-xs font-medium text-accent-fg">Most teams</span>}
            <h2 className="text-lg font-semibold">{p.name}</h2>
            <p className="mt-3">
              <span className="font-display text-5xl tabular">{fmtNumber(p.monthly_price_cents / 100, { style: "currency", currency: p.currency, maximumFractionDigits: 0 })}</span>
              <span className="text-sm text-fg-muted"> / month</span>
            </p>
            <ul className="mt-6 space-y-2.5 text-sm">
              {[`${fmtNumber(p.included_credits)} AI credits / month`, `Up to ${p.max_sites} sites`, `${fmtNumber(p.max_pages_per_crawl)} pages per crawl`, `${p.max_workspaces} workspace${p.max_workspaces > 1 ? "s" : ""}`, ...p.features].map((f) => (
                <li key={f} className="flex gap-2">
                  <Check className="mt-0.5 size-4 shrink-0 text-teal" aria-hidden /> {f}
                </li>
              ))}
            </ul>
            <Button asChild className="mt-8" variant={i === 1 ? "primary" : "secondary"}>
              <Link href="/signup">Start with {p.name}</Link>
            </Button>
          </div>
        ))}
      </div>
      <p className="mt-8 text-xs text-fg-subtle">Prices are configurable per deployment. Taxes may apply. No ranking or traffic outcomes are guaranteed.</p>
    </section>
  );
}
