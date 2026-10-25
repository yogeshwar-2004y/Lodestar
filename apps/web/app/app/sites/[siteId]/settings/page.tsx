"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Link2, PlugZap, RefreshCw, Unplug } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { ConnectorModeBadge } from "@/components/app/domain";
import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, CardBody, CardHeader, Field, Input, Skeleton, Switch, Textarea } from "@/components/ui/core";
import { ApiError, http } from "@/lib/api";
import { useCan, useMeta, useSite } from "@/lib/hooks";
import { fmtDate, timeAgo } from "@/lib/utils";

type Connector = { id: string; provider: string; status: string; mode: string; last_checked_at: string | null; last_error: string | null; secrets: { name: string; fingerprint: string; rotated_at: string | null; revoked: boolean; created_at: string }[]; capabilities: { action_type: string; supported: boolean }[] };
type Verification = { method: string; status: string; verified_at: string | null; checked_at: string | null } | null;

export default function SiteSettings() {
  const { siteId } = useParams<{ siteId: string }>();
  const qc = useQueryClient();
  const meta = useMeta();
  const site = useSite(siteId);
  const canManage = useCan("site:manage");
  const canConnect = useCan("connector:manage");
  const connectors = useQuery({ queryKey: ["connectors", siteId], queryFn: () => http<Connector[]>(`/sites/${siteId}/connectors`) });
  const verification = useQuery({ queryKey: ["verification", siteId], queryFn: () => http<Verification>(`/sites/${siteId}/verification`) });
  const onErr = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Failed");
  const check = useMutation({ mutationFn: (id: string) => http<Connector>(`/sites/${siteId}/connectors/${id}/check`, { method: "POST" }), onSuccess: (c) => { qc.invalidateQueries({ queryKey: ["connectors", siteId] }); toast[c.status === "connected" ? "success" : "error"](c.status === "connected" ? "Connection healthy" : c.last_error ?? "Connection failed"); }, onError: onErr });
  const disconnect = useMutation({ mutationFn: (id: string) => http(`/sites/${siteId}/connectors/${id}`, { method: "DELETE" }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["connectors", siteId] }); toast("Disconnected — credentials revoked"); }, onError: onErr });
  const save = useMutation({ mutationFn: (body: Record<string, unknown>) => http(`/sites/${siteId}`, { method: "PATCH", json: body }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["site", siteId] }); qc.invalidateQueries({ queryKey: ["sites"] }); toast.success("Saved"); }, onError: onErr });
  const gsc = useMutation({ mutationFn: () => http<{ authorize_url?: string; synced?: boolean }>(`/integrations/gsc/authorize?site_id=${siteId}`, { method: "POST" }), onSuccess: (r) => { if (r.authorize_url) window.location.href = r.authorize_url; else { toast.success("Search Console data synced"); qc.invalidateQueries({ queryKey: ["performance", siteId] }); } }, onError: onErr });

  if (!site.data) return <Skeleton className="h-96" />;
  const s = site.data;
  const cs = s.crawl_settings as { max_pages?: number; include_paths?: string[]; exclude_paths?: string[]; respect_robots?: boolean };
  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <PageHeader title="Site settings" description={s.domain} />
      <Card>
        <CardHeader title="Ownership" />
        <CardBody>
          {s.verified_at ? (
            <Alert tone="success" title={`Verified via ${s.verification_method?.replace("_", " ")}`}>Verified {fmtDate(s.verified_at, true)}.</Alert>
          ) : (
            <Alert tone="warning" title="Not verified" action={<Button size="sm" asChild><Link href="/app/sites/new">Verify</Link></Button>}>No changes can be written to this site until ownership is verified. {verification.data && `Last check: ${timeAgo(verification.data.checked_at)}.`}</Alert>
          )}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Connectors" description="Secrets are encrypted, stored by reference and never displayed. Only a fingerprint is shown." />
        <CardBody className="space-y-3">
          {connectors.data?.length === 0 && <p className="text-[13px] text-fg-muted">No platform connected — this site is read-only.</p>}
          {connectors.data?.map((c) => (
            <div key={c.id} className="rounded-xl border border-border p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="flex items-center gap-2 font-medium capitalize"><PlugZap className="size-4 text-teal" /> {c.provider} <ConnectorModeBadge mode={c.mode} /> <Badge tone={c.status === "connected" ? "success" : c.status === "disconnected" ? "neutral" : "danger"} dot>{c.status}</Badge></p>
                {canConnect && (
                  <div className="flex gap-2">
                    <Button size="sm" variant="secondary" onClick={() => check.mutate(c.id)} loading={check.isPending && check.variables === c.id}><RefreshCw /> Test</Button>
                    {c.status !== "disconnected" && <Button size="sm" variant="danger-outline" onClick={() => disconnect.mutate(c.id)}><Unplug /> Disconnect</Button>}
                  </div>
                )}
              </div>
              {c.last_error && <p className="mt-2 text-[12.5px] text-danger">{c.last_error}</p>}
              <p className="mt-2 text-[12px] text-fg-subtle">Last checked {timeAgo(c.last_checked_at)} · {c.capabilities.filter((x) => x.supported).length} write capabilities</p>
              <ul className="mt-2 flex flex-wrap gap-2">
                {c.secrets.map((sec) => (
                  <li key={sec.name}><Badge tone={sec.revoked ? "danger" : "neutral"}><KeyRound className="size-3" /> {sec.name} · ••••{sec.fingerprint.slice(-4)} {sec.revoked ? "revoked" : `· added ${fmtDate(sec.created_at)}`}</Badge></li>
                ))}
              </ul>
            </div>
          ))}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Google Search Console" description="Read-only OAuth access to Search Analytics for this property." />
        <CardBody className="space-y-3">
          {!meta.data?.integrations.gsc && !meta.data?.demo_mode && <Alert tone="warning" title="Not configured">Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET on the server (docs/setup/search-console.md).</Alert>}
          {meta.data?.demo_mode && !meta.data.integrations.gsc && <p className="text-[13px] text-fg-muted">Demo mode: syncing loads clearly labelled fixture data instead of real Search Console data.</p>}
          {canConnect && <Button variant="secondary" onClick={() => gsc.mutate()} loading={gsc.isPending}><Link2 /> {meta.data?.integrations.gsc ? "Connect Search Console" : "Load demo Search Console data"}</Button>}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Crawl scope" />
        <CardBody>
          <CrawlForm initial={cs} disabled={!canManage} onSave={(v) => save.mutate({ crawl_settings: v })} />
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Business goals" description="Used by the Strategy Agent to prioritise." />
        <CardBody>
          <form onSubmit={(e) => { e.preventDefault(); save.mutate({ business_goals: new FormData(e.currentTarget).get("goals") }); }} className="space-y-3">
            <Textarea name="goals" defaultValue={s.business_goals ?? ""} disabled={!canManage} aria-label="Business goals" />
            {canManage && <Button type="submit" variant="secondary">Save</Button>}
          </form>
        </CardBody>
      </Card>
    </div>
  );
}

function CrawlForm({ initial, disabled, onSave }: { initial: { max_pages?: number; include_paths?: string[]; exclude_paths?: string[]; respect_robots?: boolean }; disabled: boolean; onSave: (v: Record<string, unknown>) => void }) {
  const [v, setV] = React.useState({ max_pages: initial.max_pages ?? 100, include: (initial.include_paths ?? []).join(", "), exclude: (initial.exclude_paths ?? []).join(", "), respect_robots: initial.respect_robots ?? true });
  const split = (x: string) => x.split(",").map((s) => s.trim()).filter(Boolean);
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSave({ max_pages: v.max_pages, include_paths: split(v.include), exclude_paths: split(v.exclude), respect_robots: v.respect_robots }); }} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Max pages" htmlFor="mp" hint="Capped by your plan"><Input id="mp" type="number" min={1} value={v.max_pages} disabled={disabled} onChange={(e) => setV({ ...v, max_pages: Number(e.target.value) })} /></Field>
        <Field label="Include paths" htmlFor="inc"><Input id="inc" value={v.include} disabled={disabled} onChange={(e) => setV({ ...v, include: e.target.value })} /></Field>
        <Field label="Exclude paths" htmlFor="exc"><Input id="exc" value={v.exclude} disabled={disabled} onChange={(e) => setV({ ...v, exclude: e.target.value })} /></Field>
      </div>
      <label className="flex items-center gap-2 text-[13px]"><Switch checked={v.respect_robots} disabled={disabled} onCheckedChange={(x) => setV({ ...v, respect_robots: x })} label="Respect robots.txt" /> Respect robots.txt</label>
      {!disabled && <Button type="submit" variant="secondary">Save crawl settings</Button>}
    </form>
  );
}
