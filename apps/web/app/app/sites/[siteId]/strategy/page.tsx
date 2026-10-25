"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, ListOrdered, Target } from "lucide-react";
import { useParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { FixButton } from "@/components/app/fix-button";
import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, CardBody, CardHeader, DemoBadge, EmptyState, Skeleton, Table, Tabs, TabsContent, TabsList, TabsTrigger, Td, Th } from "@/components/ui/core";
import { ApiError, http } from "@/lib/api";
import { useCan } from "@/lib/hooks";
import { fmtDate, fmtNumber, pathOf } from "@/lib/utils";

type PlanSummary = { id: string; title: string; created_at: string };
type Plan = { id: string; title: string; summary: string; created_at: string; goals: { caveats?: string[]; keyword_opportunities?: { query: string; page_url: string | null; reason: string; source: string }[] }; agent: { provider: string; model: string; note: string | null } | null; items: { id: string; finding_id: string | null; action_type: string; title: string; rationale: string; priority: number; impact: string; effort: string; evidence_ids: string[] }[] };
type Keywords = { clusters: { id: string; name: string; intent: string | null; queries: number; clicks: number; impressions: number; opportunity_score: number | null; source: string }[]; queries: { id: string; query: string; page: string | null; clicks: number; impressions: number; ctr: number | null; position: number | null; search_volume: number | null; source: string }[]; providers: Record<string, string> };

export default function Strategy() {
  const { siteId } = useParams<{ siteId: string }>();
  const qc = useQueryClient();
  const canPlan = useCan("plan:create");
  const plans = useQuery({ queryKey: ["plans", siteId], queryFn: () => http<PlanSummary[]>(`/sites/${siteId}/plans`) });
  const [wf, setWf] = React.useState<string | null>(null);
  const workflow = useQuery({
    queryKey: ["workflow", wf],
    queryFn: () => http<{ status: string; state: { plan_id?: string } }>(`/workflows/${wf}`),
    enabled: !!wf,
    refetchInterval: (q) => (q.state.data?.status === "completed" || q.state.data?.status === "failed" ? false : 1500),
  });
  React.useEffect(() => {
    if (workflow.data?.status === "completed") {
      qc.invalidateQueries({ queryKey: ["plans", siteId] });
      setWf(null);
      toast.success("New plan ready");
    }
  }, [workflow.data, qc, siteId]);
  const latest = plans.data?.[0];
  const plan = useQuery({ queryKey: ["plan", latest?.id], queryFn: () => http<Plan>(`/plans/${latest!.id}`), enabled: !!latest });
  const kw = useQuery({ queryKey: ["keywords", siteId], queryFn: () => http<Keywords>(`/sites/${siteId}/keywords`) });
  const generate = useMutation({
    mutationFn: () => http<{ id: string }>(`/sites/${siteId}/plans`, { method: "POST" }),
    onSuccess: (r) => setWf(r.id),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not start planning"),
  });
  const isDemo = kw.data?.queries.some((q) => q.source === "demo_fixture");

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        title="Strategy & keyword intelligence"
        description="A prioritised plan from the Strategy Agent, and query groups from your own Search Console data — every number shows where it came from."
        actions={canPlan && <Button onClick={() => generate.mutate()} loading={generate.isPending || !!wf}><ListOrdered /> {wf ? "Planning…" : "Generate new plan"}</Button>}
      />
      <Tabs defaultValue="plan">
        <TabsList className="mb-4">
          <TabsTrigger value="plan">Action plan</TabsTrigger>
          <TabsTrigger value="keywords">Query groups</TabsTrigger>
          <TabsTrigger value="opportunities">Content opportunities</TabsTrigger>
        </TabsList>
        <TabsContent value="plan">
          {plans.isLoading || plan.isLoading ? <Skeleton className="h-64" /> : !plan.data ? (
            <Card><EmptyState icon={Target} title="No plan yet" action={canPlan && <Button onClick={() => generate.mutate()}>Generate plan</Button>}>Plans are generated automatically after each crawl, or on demand.</EmptyState></Card>
          ) : (
            <Card>
              <CardHeader
                title={plan.data.title}
                description={`${plan.data.summary} · ${fmtDate(plan.data.created_at, true)}`}
                action={plan.data.agent && <Badge tone={plan.data.agent.provider === "deterministic" ? "warning" : "accent"}>{plan.data.agent.provider === "deterministic" ? "Rule-based ordering" : plan.data.agent.model}</Badge>}
              />
              <CardBody>
                <ol className="space-y-2">
                  {plan.data.items.map((it) => (
                    <li key={it.id} className="flex items-start gap-3 rounded-xl border border-border p-3">
                      <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-bg-subtle font-mono text-[12px] tabular">{it.priority}</span>
                      <div className="min-w-0 flex-1">
                        <p className="text-[13.5px] font-medium">{it.title}</p>
                        <p className="text-[12.5px] text-fg-muted">{it.rationale}</p>
                        <div className="mt-1.5 flex flex-wrap gap-1.5">
                          <Badge tone={it.impact === "high" ? "accent" : "neutral"}>impact {it.impact}</Badge>
                          <Badge>effort {it.effort}</Badge>
                          <Badge tone="neutral"><span className="font-mono">{it.action_type}</span></Badge>
                        </div>
                      </div>
                    </li>
                  ))}
                </ol>
                {plan.data.goals.caveats?.length ? <p className="mt-4 text-[12px] text-fg-subtle">{plan.data.goals.caveats.join(" ")}</p> : null}
              </CardBody>
            </Card>
          )}
        </TabsContent>
        <TabsContent value="keywords">
          <Card>
            <CardHeader title="Search queries" description={kw.data?.providers.gsc} action={isDemo ? <DemoBadge /> : null} />
            {kw.data && kw.data.queries.length === 0 ? (
              <EmptyState icon={Database} title="No query data">Connect Google Search Console in Site settings to see real queries for this site.</EmptyState>
            ) : (
              <Table>
                <thead><tr><Th>Query</Th><Th className="hidden md:table-cell">Page</Th><Th className="text-right">Clicks</Th><Th className="text-right">Impr.</Th><Th className="text-right">CTR</Th><Th className="text-right">Avg pos.</Th><Th className="hidden md:table-cell">Volume</Th><Th>Source</Th></tr></thead>
                <tbody>
                  {kw.data?.queries.map((q) => (
                    <tr key={q.id}>
                      <Td className="font-medium">{q.query}</Td>
                      <Td className="hidden max-w-[220px] truncate font-mono text-[12px] md:table-cell">{q.page ? pathOf(q.page) : "—"}</Td>
                      <Td className="text-right tabular">{fmtNumber(q.clicks)}</Td>
                      <Td className="text-right tabular">{fmtNumber(q.impressions)}</Td>
                      <Td className="text-right tabular">{q.ctr !== null ? `${(q.ctr * 100).toFixed(1)}%` : "—"}</Td>
                      <Td className="text-right tabular">{q.position?.toFixed(1) ?? "—"}</Td>
                      <Td className="hidden text-fg-subtle md:table-cell">{q.search_volume ?? "not available"}</Td>
                      <Td><Badge tone={q.source === "gsc" ? "success" : "warning"}>{q.source === "gsc" ? "Search Console" : "demo fixture"}</Badge></Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
            <CardBody className="pt-3"><p className="text-[12px] text-fg-subtle">{kw.data?.providers.paid}</p></CardBody>
          </Card>
        </TabsContent>
        <TabsContent value="opportunities">
          <Card>
            <CardHeader title="Snippet & content opportunities" description="Queries with impressions but low CTR at good positions — derived only from the query data shown." />
            <CardBody className="space-y-2">
              {!plan.data?.goals.keyword_opportunities?.length && <Alert tone="info">No opportunities found in the available query data.</Alert>}
              {plan.data?.goals.keyword_opportunities?.map((o) => (
                <div key={o.query} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border p-3">
                  <div>
                    <p className="text-[13.5px] font-medium">“{o.query}”</p>
                    <p className="text-[12.5px] text-fg-muted">{o.reason}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {o.source !== "gsc" && <DemoBadge />}
                    {o.page_url && <FixButton siteId={siteId} url={o.page_url} action="meta_description" label="Improve snippet" />}
                  </div>
                </div>
              ))}
            </CardBody>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
