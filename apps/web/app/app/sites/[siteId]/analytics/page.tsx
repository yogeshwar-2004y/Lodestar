"use client";

import { useQuery } from "@tanstack/react-query";
import { LineChart as LineIcon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { StatCard, TrendChart } from "@/components/app/domain";
import { PageHeader } from "@/components/app/page-header";
import { Alert, Badge, Card, CardBody, CardHeader, DemoBadge, EmptyState, Skeleton, Table, Tabs, TabsList, TabsTrigger, Td, Th } from "@/components/ui/core";
import { http } from "@/lib/api";
import { fmtDate, fmtNumber, pathOf } from "@/lib/utils";

type Perf = {
  connected: boolean; source: string | null; is_demo_data: boolean; data_through: string | null;
  series: { date: string; clicks: number; impressions: number; ctr: number; position: number | null }[];
  totals: { clicks: number; impressions: number };
  top_pages: { page: string; clicks: number; impressions: number }[];
  annotations: { id: string; date: string; kind: string; title: string; change_set_id: string | null }[];
  caveats: string[];
};

export default function Analytics() {
  const { siteId } = useParams<{ siteId: string }>();
  const [days, setDays] = React.useState("90");
  const [metric, setMetric] = React.useState<"clicks" | "impressions" | "ctr" | "position">("clicks");
  const q = useQuery({ queryKey: ["performance", siteId, days], queryFn: () => http<Perf>(`/sites/${siteId}/performance?days=${days}`) });
  const d = q.data;
  const ctr = d && d.totals.impressions ? d.totals.clicks / d.totals.impressions : null;
  const positions = d?.series.filter((s) => s.position !== null).map((s) => s.position!) ?? [];
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        title="Analytics"
        description="Google Search Console performance with deployment annotations. Technical fix verification is tracked separately from search outcomes."
        eyebrow={d?.is_demo_data ? <DemoBadge label="Demo fixture data — not real Search Console" /> : d?.source === "gsc" ? <Badge tone="success">Google Search Console</Badge> : null}
        actions={
          <Tabs value={days} onValueChange={setDays}>
            <TabsList>{["28", "90", "180"].map((x) => <TabsTrigger key={x} value={x}>{x}d</TabsTrigger>)}</TabsList>
          </Tabs>
        }
      />
      {q.isLoading ? <Skeleton className="h-96" /> : !d?.series.length ? (
        <Card><EmptyState icon={LineIcon} title="No Search Console data" action={<Link className="text-[13px] text-accent hover:underline" href={`/app/sites/${siteId}/settings`}>Connect Search Console</Link>}>Once connected and synced, clicks, impressions, CTR and position appear here. Data is delayed about 2–3 days.</EmptyState></Card>
      ) : (
        <div className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Clicks" value={fmtNumber(d.totals.clicks)} />
            <StatCard label="Impressions" value={fmtNumber(d.totals.impressions)} />
            <StatCard label="CTR" value={ctr === null ? "—" : `${(ctr * 100).toFixed(2)}%`} />
            <StatCard label="Avg. position" value={positions.length ? (positions.reduce((a, b) => a + b, 0) / positions.length).toFixed(1) : "—"} hint="Lower is better" />
          </div>
          <Card>
            <CardHeader
              title="Performance over time"
              description={`Data through ${fmtDate(d.data_through)} · ◆ marks verified changes and rollbacks`}
              action={<Tabs value={metric} onValueChange={(v) => setMetric(v as typeof metric)}><TabsList>{(["clicks", "impressions", "ctr", "position"] as const).map((m) => <TabsTrigger key={m} value={m} className="capitalize">{m}</TabsTrigger>)}</TabsList></Tabs>}
            />
            <CardBody>
              <TrendChart data={d.series} dataKey={metric} height={300} annotations={d.annotations} color={metric === "position" ? "var(--teal)" : "var(--accent)"} />
            </CardBody>
          </Card>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader title="Top pages" />
              <Table>
                <thead><tr><Th>Page</Th><Th className="text-right">Clicks</Th><Th className="text-right">Impressions</Th></tr></thead>
                <tbody>{d.top_pages.map((p) => <tr key={p.page}><Td className="max-w-[260px] truncate font-mono text-[12px]">{pathOf(p.page)}</Td><Td className="text-right tabular">{fmtNumber(p.clicks)}</Td><Td className="text-right tabular">{fmtNumber(p.impressions)}</Td></tr>)}</tbody>
              </Table>
            </Card>
            <Card>
              <CardHeader title="Annotations" description="Changes made through Lodestar" />
              <CardBody className="space-y-2">
                {d.annotations.length === 0 && <p className="text-[13px] text-fg-muted">No changes in this period.</p>}
                {d.annotations.map((a) => (
                  <div key={a.id} className="flex items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-[13px]">
                    <span><Badge tone={a.kind === "rollback" ? "teal" : "accent"}>{a.kind}</Badge> {a.change_set_id ? <Link href={`/app/fixes/${a.change_set_id}`} className="hover:text-accent">{a.title}</Link> : a.title}</span>
                    <span className="shrink-0 text-[12px] text-fg-subtle">{fmtDate(a.date)}</span>
                  </div>
                ))}
              </CardBody>
            </Card>
          </div>
          <Alert tone="info" title="How to read this">
            <ul className="mt-1 list-disc space-y-0.5 pl-5">{d.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
          </Alert>
        </div>
      )}
    </div>
  );
}
