"use client";

import { useQuery } from "@tanstack/react-query";
import { Wand2 } from "lucide-react";
import { useParams } from "next/navigation";

import { ChangeList } from "@/components/app/change-list";
import { ConnectorModeBadge } from "@/components/app/domain";
import { FixButton } from "@/components/app/fix-button";
import { PageHeader } from "@/components/app/page-header";
import { Alert, Badge, Card, CardBody, CardHeader, Skeleton } from "@/components/ui/core";
import { http } from "@/lib/api";
import { pathOf } from "@/lib/utils";

type Connector = { id: string; provider: string; status: string; mode: string; capabilities: { action_type: string; supported: boolean; write_mode: string; rollback_supported: boolean; notes: string | null }[] };
type Finding = { id: string; title: string; fix_action: string | null; affected_count: number };
type FindingDetail = { occurrences: { url: string; status: string }[]; change_sets: { page_id: string | null }[] };

export default function FixCenter() {
  const { siteId } = useParams<{ siteId: string }>();
  const connectors = useQuery({ queryKey: ["connectors", siteId], queryFn: () => http<Connector[]>(`/sites/${siteId}/connectors`) });
  const findings = useQuery({ queryKey: ["findings", siteId, "fixable"], queryFn: () => http<Finding[]>(`/sites/${siteId}/findings?status=open`) });
  const fixable = findings.data?.filter((f) => f.fix_action === "meta_description" || f.fix_action === "title") ?? [];
  const writer = connectors.data?.find((c) => c.provider !== "gsc");
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Auto-Fix center" description="Fixable issues, what your connector is allowed to do, and every change with its diff, risk and verification." />
      <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
        <div className="space-y-5">
          <Card>
            <CardHeader title="Fixable now" description="The Execution Agent drafts a patch; nothing is written until policy and approval allow it." />
            <CardBody className="space-y-4">
              {findings.isLoading && <Skeleton className="h-24" />}
              {!findings.isLoading && fixable.length === 0 && <p className="text-[13px] text-fg-muted">No automatically fixable issues are open.</p>}
              {fixable.map((f) => <FixableFinding key={f.id} siteId={siteId} finding={f} />)}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="All changes for this site" />
            <ChangeList siteId={siteId} emptyTitle="No changes yet" emptyBody="Draft a fix from an issue above." />
          </Card>
        </div>
        <Card className="h-fit">
          <CardHeader title="Connector capabilities" />
          <CardBody>
            {!writer && <Alert tone="info" title="No write connector">This site is read-only. Fixes become recommendations you apply manually.</Alert>}
            {writer && (
              <>
                <p className="mb-3 flex items-center gap-2 text-[13px] capitalize">{writer.provider} <ConnectorModeBadge mode={writer.mode} /> <Badge tone={writer.status === "connected" ? "success" : "danger"}>{writer.status}</Badge></p>
                <ul className="space-y-2">
                  {writer.capabilities.map((c) => (
                    <li key={c.action_type} className="rounded-lg border border-border px-3 py-2">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-[12.5px]">{c.action_type}</span>
                        {c.supported ? <Badge tone="success">{c.write_mode}</Badge> : <Badge>recommend</Badge>}
                      </div>
                      {c.supported && <p className="mt-1 text-[11.5px] text-fg-subtle">{c.rollback_supported ? "Rollback supported" : "No automatic rollback"}</p>}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function FixableFinding({ siteId, finding }: { siteId: string; finding: Finding }) {
  const d = useQuery({ queryKey: ["finding", finding.id], queryFn: () => http<FindingDetail>(`/findings/${finding.id}`) });
  const open = d.data?.occurrences.filter((o) => o.status === "open") ?? [];
  return (
    <div className="rounded-xl border border-border">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <p className="flex items-center gap-2 text-[13.5px] font-medium"><Wand2 className="size-4 text-accent" /> {finding.title}</p>
        <Badge>{finding.affected_count} pages</Badge>
      </div>
      <ul className="divide-y divide-border">
        {open.slice(0, 8).map((o) => (
          <li key={o.url} className="flex items-center justify-between gap-3 px-4 py-2">
            <span className="truncate font-mono text-[12.5px]">{pathOf(o.url)}</span>
            <FixButton siteId={siteId} url={o.url} action={finding.fix_action!} findingId={finding.id} />
          </li>
        ))}
      </ul>
    </div>
  );
}
