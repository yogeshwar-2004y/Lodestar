"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { toast } from "sonner";

import { StatCard } from "@/components/app/domain";
import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, CardBody, CardHeader, Skeleton, Table, Td, Th } from "@/components/ui/core";
import { ApiError, http } from "@/lib/api";
import { useCan } from "@/lib/hooks";
import { fmtDate, fmtNumber } from "@/lib/utils";

type Usage = {
  plan: { key: string; name: string; monthly_price_cents: number; currency: string; included_credits: number; max_sites: number; max_pages_per_crawl: number } | null;
  subscription: { status: string; provider: string; current_period_end: string | null } | null;
  credits: { balance: number; pricing: Record<string, string> };
  quotas: { sites_used: number; sites_limit: number | null };
  period: string; usage: Record<string, number>; ai_cost_usd_to_date: number;
  ledger: { seq: number; delta: number; balance_after: number; reason: string; ref_type: string | null; created_at: string }[];
  reconciliation: { consistent: boolean; entries: number };
  billing_provider: string;
};
type Plan = { key: string; name: string; monthly_price_cents: number; currency: string; included_credits: number; max_sites: number };

export default function Billing() {
  const qc = useQueryClient();
  const canManage = useCan("billing:manage");
  const u = useQuery({ queryKey: ["usage"], queryFn: () => http<Usage>("/usage") });
  const plans = useQuery({ queryKey: ["plans"], queryFn: () => http<Plan[]>("/billing/plans") });
  const change = useMutation({
    mutationFn: (key: string) => http<{ provider: string; checkout_url?: string; note?: string }>(`/billing/checkout?plan_key=${key}`, { method: "POST" }),
    onSuccess: (r) => { if (r.checkout_url) window.location.href = r.checkout_url; else { toast.success(r.note ?? "Plan changed"); qc.invalidateQueries({ queryKey: ["usage"] }); } },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  if (!u.data) return <Skeleton className="h-96" />;
  const d = u.data;
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Billing & usage" description="Your plan, AI credit balance and an append-only ledger of every charge." eyebrow={d.billing_provider === "test" ? <Badge tone="warning">Test-mode payments</Badge> : <Badge tone="success">Stripe</Badge>} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Plan" value={d.plan?.name ?? "—"} hint={d.subscription ? `${d.subscription.status} · renews ${fmtDate(d.subscription.current_period_end)}` : undefined} />
        <StatCard label="AI credits" value={fmtNumber(d.credits.balance)} hint={`${fmtNumber(d.plan?.included_credits)} included monthly`} />
        <StatCard label="Sites" value={`${d.quotas.sites_used} / ${d.quotas.sites_limit ?? "∞"}`} />
        <StatCard label="AI provider cost to date" value={`$${d.ai_cost_usd_to_date.toFixed(2)}`} hint="Tracked per agent run" />
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-[1fr_360px]">
        <Card>
          <CardHeader title="Credit ledger" description={`${d.reconciliation.entries} entries · ${d.reconciliation.consistent ? "reconciled ✓" : "INCONSISTENT"}`} />
          <Table>
            <thead><tr><Th>#</Th><Th>When</Th><Th>Reason</Th><Th className="text-right">Change</Th><Th className="text-right">Balance</Th></tr></thead>
            <tbody>
              {d.ledger.map((e) => (
                <tr key={e.seq}>
                  <Td className="font-mono text-[12px] text-fg-subtle">{e.seq}</Td>
                  <Td className="text-fg-muted">{fmtDate(e.created_at, true)}</Td>
                  <Td><Badge>{e.reason.replace("_", " ")}</Badge> <span className="text-[12px] text-fg-subtle">{e.ref_type}</span></Td>
                  <Td className={`text-right tabular ${e.delta < 0 ? "text-danger" : "text-success"}`}>{e.delta > 0 ? "+" : ""}{fmtNumber(e.delta)}</Td>
                  <Td className="text-right tabular">{fmtNumber(e.balance_after)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
        <div className="space-y-5">
          <Card>
            <CardHeader title={`Usage · ${d.period}`} />
            <CardBody className="space-y-2 text-[13px]">
              {Object.keys(d.usage).length === 0 && <p className="text-fg-muted">No metered usage yet.</p>}
              {Object.entries(d.usage).map(([k, v]) => <div key={k} className="flex justify-between"><span className="text-fg-muted">{k.replaceAll("_", " ")}</span><span className="tabular">{fmtNumber(v)}</span></div>)}
              <div className="border-t border-border pt-2 text-[12px] text-fg-subtle">{Object.values(d.credits.pricing).join(" · ")}</div>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Change plan" />
            <CardBody className="space-y-2">
              {plans.data?.map((p) => (
                <div key={p.key} className="flex items-center justify-between rounded-lg border border-border px-3 py-2 text-[13px]">
                  <span><b>{p.name}</b> · {fmtNumber(p.monthly_price_cents / 100, { style: "currency", currency: p.currency, maximumFractionDigits: 0 })}/mo</span>
                  {d.plan?.key === p.key ? <Badge tone="success"><Check className="size-3" /> current</Badge> : canManage && <Button size="sm" variant="secondary" onClick={() => change.mutate(p.key)} loading={change.isPending && change.variables === p.key}>Switch</Button>}
                </div>
              ))}
              {d.billing_provider === "test" && <Alert tone="warning">Test mode: plan changes apply immediately via a signed test webhook. No payment is taken and no invoices exist.</Alert>}
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}
