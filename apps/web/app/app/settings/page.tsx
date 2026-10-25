"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, OctagonX, Trash2 } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, CardBody, CardHeader, Dialog, DialogContent, Field, Input, Skeleton } from "@/components/ui/core";
import { ApiError, http } from "@/lib/api";
import { useCan, useMeta } from "@/lib/hooks";

type Org = { id: string; name: string; kind: string; locale: string; timezone: string; kill_switch: boolean; data_retention_days: number; branding: Record<string, string> };

export default function Settings() {
  const qc = useQueryClient();
  const meta = useMeta();
  const canManage = useCan("org:manage");
  const canSettings = useCan("settings:manage");
  const canKill = useCan("killswitch:toggle");
  const canDelete = useCan("billing:manage");
  const org = useQuery({ queryKey: ["org"], queryFn: () => http<Org>("/organizations/current") });
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const onErr = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Failed");
  const save = useMutation({ mutationFn: (b: Record<string, unknown>) => http("/organizations/current", { method: "PATCH", json: b }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["org"] }); qc.invalidateQueries({ queryKey: ["session"] }); toast.success("Saved"); }, onError: onErr });
  const kill = useMutation({ mutationFn: (engaged: boolean) => http(`/organizations/current/kill-switch?engaged=${engaged}`, { method: "POST" }), onSuccess: () => { qc.invalidateQueries(); }, onError: onErr });
  const del = useMutation({ mutationFn: () => http<{ deletion_scheduled_for: string }>("/organizations/current/deletion", { method: "POST" }), onSuccess: (r) => { setConfirmDelete(false); qc.invalidateQueries(); toast(`Deletion scheduled for ${new Date(r.deletion_scheduled_for).toLocaleDateString()}`); }, onError: onErr });
  async function exportData() {
    const res = await fetch("/api/v1/organizations/current/export", { method: "POST", credentials: "include", headers: { "X-CSRF-Token": document.cookie.split("; ").find((c) => c.startsWith("ls_csrf="))?.split("=")[1] ?? "" } });
    if (!res.ok) return toast.error("Export failed");
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: "lodestar-export.json" });
    a.click();
    URL.revokeObjectURL(url);
  }
  if (!org.data) return <Skeleton className="h-96" />;
  const o = org.data;
  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <PageHeader title="Settings" description="Organization, safety controls, integrations and data." />
      <Card>
        <CardHeader title="Organization" />
        <CardBody>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); save.mutate({ name: f.get("name"), locale: f.get("locale"), timezone: f.get("timezone"), branding: { ...o.branding, primary_color: f.get("color"), agency_name: f.get("agency") || undefined } }); }}>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Name" htmlFor="n"><Input id="n" name="name" defaultValue={o.name} disabled={!canManage} /></Field>
              <Field label="Type" htmlFor="k"><Input id="k" value={o.kind} disabled /></Field>
              <Field label="Locale" htmlFor="l"><Input id="l" name="locale" defaultValue={o.locale} disabled={!canManage} /></Field>
              <Field label="Time zone" htmlFor="t"><Input id="t" name="timezone" defaultValue={o.timezone} disabled={!canManage} /></Field>
              <Field label="Report brand name" htmlFor="a"><Input id="a" name="agency" defaultValue={o.branding.agency_name ?? ""} disabled={!canManage} /></Field>
              <Field label="Brand color" htmlFor="c"><Input id="c" name="color" type="color" defaultValue={o.branding.primary_color ?? "#4f46e5"} className="h-9 p-1" disabled={!canManage} /></Field>
            </div>
            {canManage && <Button type="submit" loading={save.isPending}>Save</Button>}
          </form>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Emergency kill switch" description="Blocks every execution across all sites and cancels queued work." />
        <CardBody>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Badge tone={o.kill_switch ? "danger" : "success"} dot>{o.kill_switch ? "Engaged" : "Off"}</Badge>
            {canKill && <Button variant={o.kill_switch ? "secondary" : "danger"} onClick={() => kill.mutate(!o.kill_switch)} loading={kill.isPending}><OctagonX /> {o.kill_switch ? "Release" : "Engage kill switch"}</Button>}
          </div>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Integrations & secrets status" description="Server-side configuration. Secret values are never shown." />
        <CardBody className="space-y-2 text-[13px]">
          <Row label="AI provider" value={meta.data?.ai_mode === "llm" ? <Badge tone="success">{meta.data.ai_model}</Badge> : <Badge tone="warning">Deterministic fallback{meta.data?.ai_note ? ` — ${meta.data.ai_note}` : ""}</Badge>} />
          {Object.entries(meta.data?.integrations ?? {}).map(([k, v]) => <Row key={k} label={k === "gsc" ? "Google Search Console" : k[0].toUpperCase() + k.slice(1)} value={v ? <Badge tone="success">configured</Badge> : <Badge>requires credentials</Badge>} />)}
          <Row label="Environment" value={<Badge>{meta.data?.environment}{meta.data?.demo_mode ? " · demo mode" : ""}</Badge>} />
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Data retention, export & deletion" />
        <CardBody className="space-y-4">
          <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); save.mutate({ data_retention_days: Number(new FormData(e.currentTarget).get("ret")) }); }}>
            <Field label="Retain crawl snapshots & logs (days)" htmlFor="ret"><Input id="ret" name="ret" type="number" min={30} max={3650} defaultValue={o.data_retention_days} disabled={!canManage} className="w-40" /></Field>
            {canManage && <Button variant="secondary" type="submit">Save</Button>}
          </form>
          <div className="flex flex-wrap gap-2">
            {canSettings && <Button variant="secondary" onClick={exportData}><Download /> Export all data (JSON)</Button>}
            {canDelete && <Button variant="danger-outline" onClick={() => setConfirmDelete(true)}><Trash2 /> Delete organization</Button>}
          </div>
        </CardBody>
      </Card>
      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent title="Delete organization?" description="This engages the kill switch now and permanently deletes all data after a 30-day grace period.">
          <Alert tone="danger">Connector credentials are revoked at deletion. Audit records are purged with the organization.</Alert>
          <div className="mt-4 flex justify-end gap-2"><Button variant="ghost" onClick={() => setConfirmDelete(false)}>Cancel</Button><Button variant="danger" onClick={() => del.mutate()} loading={del.isPending}>Schedule deletion</Button></div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="flex items-center justify-between gap-3 border-b border-border pb-2 last:border-0">{label}<span>{value}</span></div>;
}
