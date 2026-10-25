"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CheckCircle2, EyeOff, Layers, ShieldCheck } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { KindBadge, SeverityBadge, StatusBadge } from "@/components/app/domain";
import { FixButton } from "@/components/app/fix-button";
import { ErrorState, PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, EmptyState, NativeSelect, Skeleton } from "@/components/ui/core";
import { http } from "@/lib/api";
import { useCan } from "@/lib/hooks";
import { cn, pathOf } from "@/lib/utils";

type Finding = { id: string; rule_key: string; status: string; severity: string; kind: string; category: string; title: string; summary: string; remediation: string; fix_action: string | null; affected_count: number; evidence: Record<string, unknown> };
type FindingDetail = { finding: Finding; occurrences: { id: string; url: string; page_id: string | null; evidence: Record<string, unknown>; status: string }[]; change_sets: { id: string; status: string; title: string; page_id: string | null }[] };
type AuditRun = { provider: string; model: string; note: string | null; output: { summary: string; clusters: { title: string; explanation: string; finding_ids: string[]; priority: string; deterministic: boolean }[]; limitations: string[] } } | null;

const CATS = ["metadata", "content", "indexability", "links", "structured_data", "media", "performance", "crawlability"];

export default function AuditCenter() {
  const { siteId } = useParams<{ siteId: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const [severity, setSeverity] = React.useState("");
  const [kind, setKind] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [status, setStatus] = React.useState("open");
  const selected = search.get("finding");
  const qs = new URLSearchParams({ status, ...(severity && { severity }), ...(kind && { kind }), ...(category && { category }) });
  const findings = useQuery({ queryKey: ["findings", siteId, qs.toString()], queryFn: () => http<Finding[]>(`/sites/${siteId}/findings?${qs}`) });
  const audit = useQuery({ queryKey: ["latest-audit", siteId], queryFn: () => http<AuditRun>(`/sites/${siteId}/agents/latest-audit`) });
  const counts = React.useMemo(() => {
    const c: Record<string, number> = {};
    findings.data?.forEach((f) => (c[f.category] = (c[f.category] ?? 0) + 1));
    return c;
  }, [findings.data]);
  const current = selected ?? findings.data?.[0]?.id;
  const select = (id: string) => router.replace(`/app/sites/${siteId}/audit?finding=${id}`, { scroll: false });

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Audit center" description="Every issue with its evidence, affected pages and remediation. Deterministic defects are verifiable; heuristic items are opportunities to review." />

      {audit.data && (
        <Card className="mb-5 overflow-hidden">
          <div className="flex flex-wrap items-start gap-4 bg-gradient-to-r from-accent-soft/70 to-transparent p-5">
            <span className="grid size-9 place-items-center rounded-xl bg-accent text-accent-fg"><Bot className="size-4.5" /></span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-[13px] font-semibold">Audit Agent summary</p>
                <Badge tone={audit.data.provider === "deterministic" ? "warning" : "accent"}>{audit.data.provider === "deterministic" ? "Deterministic fallback" : audit.data.model}</Badge>
              </div>
              <p className="mt-1 text-[13.5px] text-fg-muted">{audit.data.output.summary}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {audit.data.output.clusters.slice(0, 6).map((c) => (
                  <button key={c.title} onClick={() => c.finding_ids[0] && select(c.finding_ids[0])} className="rounded-lg border border-border bg-surface px-2.5 py-1.5 text-left text-[12.5px] hover:border-border-strong">
                    <span className="font-medium">{c.title}</span> <Badge tone={c.priority === "now" ? "danger" : c.priority === "next" ? "warning" : "neutral"}>{c.priority}</Badge>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </Card>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1.5">
          <CatChip active={!category} onClick={() => setCategory("")} label="All" count={findings.data?.length} />
          {CATS.filter((c) => counts[c] || category === c).map((c) => (
            <CatChip key={c} active={category === c} onClick={() => setCategory(c)} label={c.replace("_", " ")} count={counts[c]} />
          ))}
        </div>
        <div className="ml-auto flex flex-wrap gap-2">
          <NativeSelect aria-label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="">All severities</option>
            {["critical", "high", "medium", "low", "info"].map((s) => <option key={s}>{s}</option>)}
          </NativeSelect>
          <NativeSelect aria-label="Type" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Deterministic + heuristic</option>
            <option value="deterministic">Deterministic only</option>
            <option value="heuristic">Heuristic only</option>
          </NativeSelect>
          <NativeSelect aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="open">Open</option>
            <option value="resolved">Resolved</option>
            <option value="ignored">Ignored</option>
            <option value="all">All</option>
          </NativeSelect>
        </div>
      </div>

      {findings.error && <ErrorState error={findings.error} />}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,420px)_1fr]">
        <Card className="max-h-[calc(100dvh-220px)] overflow-y-auto">
          {findings.isLoading && <div className="space-y-2 p-3">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-14" />)}</div>}
          {findings.data?.length === 0 && <EmptyState icon={CheckCircle2} title="Nothing here">No findings match these filters.</EmptyState>}
          <ul className="divide-y divide-border">
            {findings.data?.map((f) => (
              <li key={f.id}>
                <button onClick={() => select(f.id)} className={cn("w-full px-4 py-3 text-left transition-colors hover:bg-bg-subtle", current === f.id && "bg-accent-soft/50")} aria-current={current === f.id}>
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-[13.5px] font-medium">{f.title}</span>
                    <SeverityBadge severity={f.severity} />
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[12px] text-fg-subtle">
                    <span>{f.affected_count} affected</span>·<span>{f.category.replace("_", " ")}</span>·<span>{f.kind}</span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </Card>
        {current ? <FindingPanel siteId={siteId} id={current} /> : <Card><EmptyState icon={Layers} title="Select a finding" /></Card>}
      </div>
    </div>
  );
}

function CatChip({ active, onClick, label, count }: { active: boolean; onClick: () => void; label: string; count?: number }) {
  return (
    <button onClick={onClick} className={cn("rounded-full border px-3 py-1 text-[12.5px] capitalize transition-colors", active ? "border-accent bg-accent-soft text-accent" : "border-border text-fg-muted hover:border-border-strong")} aria-pressed={active}>
      {label} {count !== undefined && <span className="tabular opacity-70">{count}</span>}
    </button>
  );
}

function FindingPanel({ siteId, id }: { siteId: string; id: string }) {
  const qc = useQueryClient();
  const canManage = useCan("finding:manage");
  const { data, isLoading } = useQuery({ queryKey: ["finding", id], queryFn: () => http<FindingDetail>(`/findings/${id}`) });
  const setStatus = useMutation({
    mutationFn: (s: string) => http(`/findings/${id}/status?status=${s}`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["findings", siteId] });
      qc.invalidateQueries({ queryKey: ["finding", id] });
      toast.success("Updated");
    },
  });
  if (isLoading || !data) return <Card className="p-5"><Skeleton className="h-64" /></Card>;
  const f = data.finding;
  const changeByPage = new Map(data.change_sets.map((c) => [c.page_id, c]));
  return (
    <Card>
      <CardHeader
        title={f.title}
        description={f.summary}
        action={
          canManage && f.status === "open" ? (
            <Button variant="ghost" size="sm" onClick={() => setStatus.mutate("ignored")}><EyeOff /> Ignore</Button>
          ) : f.status === "ignored" && canManage ? (
            <Button variant="ghost" size="sm" onClick={() => setStatus.mutate("open")}>Reopen</Button>
          ) : null
        }
      />
      <CardBody className="space-y-5">
        <div className="flex flex-wrap gap-2">
          <SeverityBadge severity={f.severity} />
          <KindBadge kind={f.kind} />
          <Badge>{f.category.replace("_", " ")}</Badge>
          <Badge tone="neutral"><span className="font-mono">{f.rule_key}</span></Badge>
          {f.status !== "open" && <StatusBadge status={f.status === "resolved" ? "completed" : f.status} />}
        </div>
        {f.kind === "heuristic" && (
          <p className="rounded-lg bg-teal-soft px-3 py-2 text-[12.5px] text-teal">Heuristic opportunity — based on guidelines, not a verified defect. Use judgement.</p>
        )}
        <section>
          <h3 className="mb-1.5 flex items-center gap-1.5 text-[13px] font-semibold"><ShieldCheck className="size-4 text-teal" /> Remediation</h3>
          <p className="text-[13.5px] text-fg-muted">{f.remediation}</p>
          {["canonical_issues", "redirect_chain", "noindex_in_sitemap", "broken_internal_links", "invalid_structured_data"].includes(f.rule_key) && (
            <p className="mt-2 text-[12.5px] text-fg-subtle">This type of change is review-only or restricted in V1 — apply it manually after review.</p>
          )}
        </section>
        <section>
          <h3 className="mb-2 text-[13px] font-semibold">Affected pages ({data.occurrences.length})</h3>
          <ul className="divide-y divide-border rounded-xl border border-border">
            {data.occurrences.slice(0, 100).map((o) => {
              const cs = o.page_id ? changeByPage.get(o.page_id) : undefined;
              return (
                <li key={o.id} className="px-3 py-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="min-w-0 truncate font-mono text-[12.5px]">{pathOf(o.url)}</span>
                    <span className="flex items-center gap-1.5">
                      {o.status === "fixed" && <Badge tone="success">fixed</Badge>}
                      {cs ? (
                        <a href={`/app/fixes/${cs.id}`} className="text-[12px] text-accent hover:underline"><StatusBadge status={cs.status} /></a>
                      ) : (
                        f.fix_action && o.status === "open" && <FixButton siteId={siteId} url={o.url} action={f.fix_action} findingId={f.id} />
                      )}
                    </span>
                  </div>
                  {Object.keys(o.evidence).length > 0 && (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-[11.5px] text-fg-subtle">Evidence</summary>
                      <pre className="mt-1 max-h-48 overflow-auto rounded-md bg-bg-subtle p-2 font-mono text-[11px]">{JSON.stringify(o.evidence, null, 2)}</pre>
                    </details>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      </CardBody>
    </Card>
  );
}
