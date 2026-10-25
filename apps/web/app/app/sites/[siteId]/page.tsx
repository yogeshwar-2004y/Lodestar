"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Bot, Radar, RefreshCw, Wand2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { CategoryBars, HealthRing, KindBadge, SeverityBadge, SeverityBars, Sparkline, StatCard, StatusBadge, TrendChart } from "@/components/app/domain";
import { ErrorState, FadeIn, PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, CardBody, CardHeader, DemoBadge, EmptyState, Skeleton, Tooltip } from "@/components/ui/core";
import { ApiError, http, newIdempotencyKey } from "@/lib/api";
import { useCan } from "@/lib/hooks";
import { fmtNumber, timeAgo } from "@/lib/utils";

type Overview = {
  site: { id: string; name: string; domain: string; health_score: number | null; health_breakdown: { categories?: Record<string, number>; methodology?: string }; last_crawl_at: string | null; verified_at: string | null; is_demo: boolean; platform: string };
  pages: number;
  findings_by_severity: Record<string, number>;
  findings_by_kind: Record<string, number>;
  top_findings: { id: string; title: string; severity: string; kind: string; affected_count: number; category: string; fix_action: string | null }[];
  changes_by_status: Record<string, number>;
  health_history: { at: string | null; score: number | null; pages: number }[];
};
type Crawl = { id: string; status: string; pages_crawled: number; created_at: string; finished_at: string | null; error: string | null };
type Workflow = { id: string; kind: string; status: string; created_at: string; steps: { name: string; status: string }[]; agent_runs: { agent: string; provider: string }[] };
type ChangeSet = { id: string; title: string; status: string; updated_at: string; is_fixture: boolean };

export default function SiteOverview() {
  const { siteId } = useParams<{ siteId: string }>();
  const qc = useQueryClient();
  const canCrawl = useCan("crawl:run");
  const ov = useQuery({ queryKey: ["overview", siteId], queryFn: () => http<Overview>(`/sites/${siteId}/overview`) });
  const crawls = useQuery({
    queryKey: ["crawls", siteId],
    queryFn: () => http<Crawl[]>(`/sites/${siteId}/crawls`),
    refetchInterval: (q) => (q.state.data?.some((c) => ["queued", "running"].includes(c.status)) ? 2500 : false),
  });
  const workflows = useQuery({ queryKey: ["workflows", siteId], queryFn: () => http<Workflow[]>(`/sites/${siteId}/workflows`) });
  const changes = useQuery({ queryKey: ["changes", siteId, "recent"], queryFn: () => http<{ items: ChangeSet[] }>(`/change-sets?site_id=${siteId}&limit=6`) });
  const perf = useQuery({ queryKey: ["performance", siteId, 28], queryFn: () => http<{ series: { date: string; clicks: number }[]; totals: { clicks: number; impressions: number }; is_demo_data: boolean; connected: boolean }>(`/sites/${siteId}/performance?days=28`) });

  const active = crawls.data?.find((c) => ["queued", "running"].includes(c.status));
  const crawl = useMutation({
    mutationFn: () => http<Crawl & { deduplicated: boolean }>(`/sites/${siteId}/crawls`, { json: {}, idempotencyKey: newIdempotencyKey("crawl") }),
    onSuccess: (r) => {
      toast.success(r.deduplicated ? "A crawl is already running" : "Crawl queued");
      qc.invalidateQueries({ queryKey: ["crawls", siteId] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not start crawl"),
  });

  // refresh dashboards when an active crawl finishes (agents run right after, so refresh again shortly)
  const wasActive = React.useRef(false);
  React.useEffect(() => {
    if (wasActive.current && !active) {
      const refresh = () => ["overview", "workflows", "changes", "site"].forEach((k) => qc.invalidateQueries({ queryKey: [k, siteId] }));
      refresh();
      const t = setTimeout(refresh, 4000);
      wasActive.current = false;
      return () => clearTimeout(t);
    }
    wasActive.current = !!active;
  }, [active, qc, siteId]);

  if (ov.error) return <ErrorState error={ov.error} />;
  const d = ov.data;
  const openTotal = d ? Object.values(d.findings_by_severity).reduce((a, b) => a + b, 0) : 0;
  const pending = d?.changes_by_status.pending_approval ?? 0;
  const done = d?.changes_by_status.completed ?? 0;
  const neverCrawled = d && !d.site.last_crawl_at && !active;

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        eyebrow={
          d && (
            <>
              <Badge>{d.site.platform}</Badge>
              {d.site.verified_at ? <Badge tone="success" dot>Verified</Badge> : <Badge tone="warning" dot>Not verified — read-only</Badge>}
              {d.site.is_demo && <DemoBadge />}
            </>
          )
        }
        title={d?.site.name ?? <Skeleton className="h-9 w-64" />}
        description={d ? `${d.site.domain} · last crawl ${timeAgo(d.site.last_crawl_at)}` : undefined}
        actions={
          canCrawl && (
            <Button onClick={() => crawl.mutate()} loading={crawl.isPending} disabled={!!active}>
              {active ? <RefreshCw className="animate-spin" /> : <Radar />} {active ? `Crawling… ${active.pages_crawled || ""}` : "Run crawl"}
            </Button>
          )
        }
      />

      {active && (
        <Alert tone="info" className="mb-6" title={active.status === "queued" ? "Crawl queued" : "Crawl in progress"}>
          Results, findings and agent summaries will appear here automatically.
        </Alert>
      )}
      {neverCrawled && (
        <Card className="mb-6">
          <EmptyState icon={Radar} title="No audit yet" action={canCrawl && <Button onClick={() => crawl.mutate()}>Run first audit</Button>}>
            Run a crawl to discover pages, detect issues and get a prioritised plan.
          </EmptyState>
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
        <FadeIn>
          <Card className="h-full">
            <CardHeader
              title="Site health"
              description={
                <Tooltip content={d?.site.health_breakdown.methodology ?? ""}>
                  <span className="cursor-help underline decoration-dotted underline-offset-2">Internal diagnostic — not a Google score</span>
                </Tooltip>
              }
            />
            <CardBody className="flex flex-col items-center">
              {ov.isLoading ? <Skeleton className="size-[132px] rounded-full" /> : <HealthRing score={d?.site.health_score} />}
              <div className="mt-4 w-full">
                <Sparkline data={(d?.health_history ?? []).map((h) => ({ score: h.score }))} dataKey="score" color="var(--teal)" />
              </div>
              <div className="mt-2 w-full">
                {d?.site.health_breakdown.categories && (
                  <CategoryBars data={Object.entries(d.site.health_breakdown.categories).map(([name, value]) => ({ name: name.replace("_", " "), value }))} />
                )}
              </div>
            </CardBody>
          </Card>
        </FadeIn>

        <div className="space-y-5">
          <FadeIn delay={0.05} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Pages crawled" value={fmtNumber(d?.pages)} />
            <StatCard label="Open issues" value={fmtNumber(openTotal)} hint={`${d?.findings_by_kind.deterministic ?? 0} deterministic · ${d?.findings_by_kind.heuristic ?? 0} heuristic`} />
            <StatCard label="Awaiting approval" value={fmtNumber(pending)} hint={<Link href="/app/approvals" className="text-accent hover:underline">Open inbox →</Link>} />
            <StatCard label="Verified fixes" value={fmtNumber(done)} hint="Confirmed in live HTML" />
          </FadeIn>

          <FadeIn delay={0.1} className="grid gap-5 xl:grid-cols-2">
            <Card>
              <CardHeader title="Top priorities" action={<Link href={`/app/sites/${siteId}/audit`} className="text-[13px] text-accent hover:underline">Audit center</Link>} />
              <CardBody className="space-y-1 px-2">
                {ov.isLoading && [0, 1, 2].map((i) => <Skeleton key={i} className="mx-3 h-10" />)}
                {d?.top_findings.length === 0 && <p className="px-3 py-4 text-[13px] text-fg-muted">No open issues. 🎉</p>}
                {d?.top_findings.map((f) => (
                  <Link key={f.id} href={`/app/sites/${siteId}/audit?finding=${f.id}`} className="flex items-center justify-between gap-3 rounded-lg px-3 py-2.5 hover:bg-bg-subtle">
                    <div className="min-w-0">
                      <p className="truncate text-[13.5px] font-medium">{f.title}</p>
                      <p className="text-[12px] text-fg-subtle">{f.affected_count} affected · {f.category.replace("_", " ")}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {f.fix_action && <Badge tone="accent"><Wand2 className="size-3" /> fixable</Badge>}
                      <SeverityBadge severity={f.severity} />
                    </div>
                  </Link>
                ))}
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Issues by severity" description={<KindLegend />} />
              <CardBody>
                <SeverityBars data={d?.findings_by_severity ?? {}} />
              </CardBody>
            </Card>
          </FadeIn>
        </div>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader
            title="Search clicks (28 days)"
            description={perf.data?.connected ? `${fmtNumber(perf.data.totals.clicks)} clicks · ${fmtNumber(perf.data.totals.impressions)} impressions` : "Connect Search Console to see performance."}
            action={perf.data?.is_demo_data ? <DemoBadge /> : <Link href={`/app/sites/${siteId}/analytics`} className="text-[13px] text-accent hover:underline">Analytics</Link>}
          />
          <CardBody>
            {perf.data?.series.length ? <TrendChart data={perf.data.series} dataKey="clicks" height={200} /> : <EmptyState icon={Bot} title="No search data yet">Search Console data appears after connecting and syncing (it&apos;s delayed ~2–3 days).</EmptyState>}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Automation activity" />
          <CardBody className="space-y-3">
            {workflows.data?.length === 0 && <p className="text-[13px] text-fg-muted">Agent workflows run after each crawl.</p>}
            {workflows.data?.slice(0, 4).map((w) => (
              <div key={w.id} className="rounded-lg border border-border p-3">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-medium capitalize">{w.kind.replace("_", " ")}</span>
                  <StatusBadge status={w.status === "completed" ? "succeeded" : w.status} />
                </div>
                <p className="mt-1 text-[12px] text-fg-subtle">
                  {w.steps.map((s) => s.name).join(" → ")} · {timeAgo(w.created_at)}
                </p>
              </div>
            ))}
          </CardBody>
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader title="Recent changes" action={<Link href={`/app/sites/${siteId}/fixes`} className="inline-flex items-center gap-1 text-[13px] text-accent hover:underline">Auto-Fix center <ArrowRight className="size-3.5" /></Link>} />
        <CardBody className="px-2">
          {changes.data?.items.length === 0 && <p className="px-3 py-3 text-[13px] text-fg-muted">No changes proposed yet.</p>}
          {changes.data?.items.map((c) => (
            <Link key={c.id} href={`/app/fixes/${c.id}`} className="flex items-center justify-between gap-3 rounded-lg px-3 py-2.5 hover:bg-bg-subtle">
              <span className="truncate text-[13.5px]">{c.title}</span>
              <span className="flex shrink-0 items-center gap-2">
                {c.is_fixture && <Badge tone="warning">Fixture</Badge>}
                <StatusBadge status={c.status} />
                <span className="hidden text-[12px] text-fg-subtle sm:inline">{timeAgo(c.updated_at)}</span>
              </span>
            </Link>
          ))}
        </CardBody>
      </Card>
    </div>
  );
}

function KindLegend() {
  return (
    <span className="inline-flex items-center gap-2">
      <KindBadge kind="deterministic" /> verifiable defects · <KindBadge kind="heuristic" /> opportunities
    </span>
  );
}

