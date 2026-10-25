"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Check, CircleSlash, FlaskConical, Hash, Pencil, Play, RotateCcw, ShieldCheck, Undo2, X } from "lucide-react";
import { useParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { ConnectorModeBadge, DiffView, RiskMeter, SerpPreview, StatusBadge, Timeline } from "@/components/app/domain";
import { ErrorState, PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, CardBody, CardHeader, Dialog, DialogContent, Field, Skeleton, Textarea } from "@/components/ui/core";
import { ApiError, http, newIdempotencyKey } from "@/lib/api";
import { useCan } from "@/lib/hooks";
import { cn, fmtDate, pathOf } from "@/lib/utils";

type Version = { id: string; version: number; patch: { action_type: string; resource: { url: string; type?: string; id?: unknown }; after: Record<string, string>; warnings?: string[]; connector?: { provider: string; mode: string } }; before: Record<string, string>; resource_version: string | null; patch_hash: string; validation: { passed?: boolean; errors?: string[]; warnings?: string[]; length?: number }; rationale: string | null; evidence_ids: string[]; created_at: string };
type ConnectorResult = { applied?: boolean; live?: boolean; resource_version?: string; message?: string };
type Verification = { verified?: boolean; pending?: boolean; method?: string; observed?: { live_html?: Record<string, string | null> } & Record<string, unknown>; details?: { fetched_url?: string } };
type Execution = { id: string; kind: string; status: string; attempt: number; connector_provider: string | null; connector_mode: string | null; connector_result: ConnectorResult; verification: Verification; error: string | null; started_at: string | null; finished_at: string | null; created_at: string };
type Detail = {
  id: string; site_id: string; title: string; status: string; action_type: string; risk_score: number | null; risk_level: string | null; source: string; is_fixture: boolean; created_at: string;
  policy_decision: { decision: string; reasons: string[]; checks?: { name: string; passed: boolean; detail: string }[]; rollback_guaranteed?: boolean } | null;
  current_version: Version | null; versions: Version[];
  approvals: { id: string; decision: string; reason: string | null; patch_hash: string; patch_version_id: string; created_at: string }[];
  executions: Execution[];
  connector: { provider: string; mode: string; status: string; write_mode: string; rollback_supported: boolean } | null;
  rollback_available: boolean; rollback_note: string | null;
  page: { title: string | null; meta_description: string | null } | null;
};
type AuditEvent = { id: string; created_at: string; action: string; actor: string | null; actor_type: string; data: Record<string, unknown> };

const ACTIVE = ["queued", "executing", "verifying", "rollback_queued"];
const TONE: Record<string, "success" | "danger" | "warning" | "teal" | undefined> = {
  "execution.verified": "success", "change_set.approved": "success", "change_set.auto_approved": "success", "rollback.completed": "teal",
  "execution.failed": "danger", "execution.verification_failed": "danger", "change_set.rejected": "danger", "rollback.failed": "danger", "change_set.revised": "warning",
};

export default function ChangeDetail() {
  const { changeId } = useParams<{ changeId: string }>();
  const qc = useQueryClient();
  const canApprove = useCan("change:approve");
  const canExecute = useCan("change:execute");
  const canPropose = useCan("change:propose");
  const q = useQuery({
    queryKey: ["change", changeId],
    queryFn: () => http<Detail>(`/change-sets/${changeId}`),
    refetchInterval: (query) => (query.state.data && ACTIVE.includes(query.state.data.status) ? 1500 : false),
  });
  const events = useQuery({
    queryKey: ["change-events", changeId, q.data?.status],
    queryFn: () => http<{ items: AuditEvent[] }>(`/audit-events?target_id=${changeId}&site_id=${q.data!.site_id}&limit=100`),
    enabled: !!q.data,
  });
  const [dialog, setDialog] = React.useState<null | "reject" | "revise" | "rollback" | "approve">(null);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["change", changeId] });
    qc.invalidateQueries({ queryKey: ["changes"] });
    qc.invalidateQueries({ queryKey: ["approvals"] });
  };
  const onErr = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Action failed");
  const v = q.data?.current_version;

  const approve = useMutation({
    mutationFn: (reason: string) => http(`/change-sets/${changeId}/approve`, { json: { patch_hash: v!.patch_hash, reason: reason || null }, idempotencyKey: newIdempotencyKey("approve") }),
    onSuccess: () => { toast.success("Approved this exact version"); setDialog(null); refresh(); },
    onError: onErr,
  });
  const reject = useMutation({
    mutationFn: (reason: string) => http(`/change-sets/${changeId}/reject`, { json: { patch_hash: v!.patch_hash, reason } }),
    onSuccess: () => { toast("Rejected"); setDialog(null); refresh(); },
    onError: onErr,
  });
  const execute = useMutation({
    mutationFn: () => http(`/change-sets/${changeId}/execute`, { json: { patch_hash: v!.patch_hash }, idempotencyKey: newIdempotencyKey("execute") }),
    onSuccess: () => { toast.success("Execution queued"); refresh(); },
    onError: onErr,
  });
  const validate = useMutation({
    mutationFn: (value?: string) => http(`/change-sets/${changeId}/validate`, { json: value ? { value } : {} }),
    onSuccess: (_, value) => { toast.success(value ? "New version created — previous approvals no longer apply" : "Dry run complete: validation and policy re-evaluated"); setDialog(null); refresh(); },
    onError: onErr,
  });
  const rollback = useMutation({
    mutationFn: (reason: string) => http(`/change-sets/${changeId}/rollback`, { json: { reason: reason || null }, idempotencyKey: newIdempotencyKey("rollback") }),
    onSuccess: () => { toast.success("Rollback queued"); setDialog(null); refresh(); },
    onError: onErr,
  });
  const cancel = useMutation({ mutationFn: () => http(`/change-sets/${changeId}/cancel`, { method: "POST" }), onSuccess: refresh, onError: onErr });

  if (q.error) return <ErrorState error={q.error} />;
  if (!q.data || !v) return <div className="mx-auto max-w-6xl space-y-4"><Skeleton className="h-16" /><Skeleton className="h-64" /></div>;
  const d = q.data;
  const field = d.action_type;
  const latestApply = d.executions.find((e) => e.kind === "apply");
  const latestRollback = d.executions.find((e) => e.kind === "rollback");
  const approvalForCurrent = d.approvals.find((a) => a.patch_version_id === v.id && a.decision !== "rejected");

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        eyebrow={
          <>
            <StatusBadge status={d.status} />
            {d.connector && <ConnectorModeBadge mode={d.connector.mode} />}
            <Badge tone={d.source === "ai" ? "accent" : "neutral"}>{d.source === "ai" ? "AI draft" : d.source === "deterministic" ? "Template draft" : "Human-written"}</Badge>
          </>
        }
        title={d.title}
        description={<span className="font-mono text-[12.5px]">{v.patch.resource.url}</span>}
        actions={
          <>
            {canPropose && ["pending_approval", "invalid", "blocked", "rejected", "failed", "approved"].includes(d.status) && (
              <Button variant="secondary" onClick={() => setDialog("revise")}><Pencil /> Revise</Button>
            )}
            {["pending_approval", "invalid", "blocked"].includes(d.status) && (
              <Button variant="secondary" onClick={() => validate.mutate(undefined)} loading={validate.isPending && !validate.variables}><FlaskConical /> Dry run</Button>
            )}
            {canApprove && d.status === "pending_approval" && (
              <>
                <Button variant="danger-outline" onClick={() => setDialog("reject")}><X /> Reject</Button>
                <Button variant="success" onClick={() => setDialog("approve")}><Check /> Approve</Button>
              </>
            )}
            {canExecute && ["approved", "failed"].includes(d.status) && approvalForCurrent && (
              <Button onClick={() => execute.mutate()} loading={execute.isPending}><Play /> {d.status === "failed" ? "Retry execution" : "Execute"}</Button>
            )}
            {d.status === "queued" && canExecute && <Button variant="ghost" onClick={() => cancel.mutate()}><CircleSlash /> Cancel</Button>}
            {canExecute && d.rollback_available && <Button variant="secondary" onClick={() => setDialog("rollback")}><Undo2 /> Roll back</Button>}
          </>
        }
      />

      {d.is_fixture && (
        <Alert tone="warning" className="mb-5" title="Fixture connector">
          Writes for this change go to the local WordPress test fixture, not a real customer website.
        </Alert>
      )}
      {d.status === "recommendation" && (
        <Alert tone="info" className="mb-5" title="Recommendation only">No connected platform can make this change automatically. Apply it manually in your CMS.</Alert>
      )}
      {ACTIVE.includes(d.status) && <ProgressBanner status={d.status} />}

      <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
        <div className="space-y-5">
          <Card>
            <CardHeader title="Before / after" description={`Version ${v.version} · immutable`} action={<HashChip hash={v.patch_hash} />} />
            <CardBody className="space-y-4">
              <DiffView field={field} before={v.before[field] ?? ""} after={v.patch.after[field] ?? ""} />
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <p className="mb-1.5 text-[11.5px] uppercase tracking-wide text-fg-subtle">Search preview (after)</p>
                  <SerpPreview url={v.patch.resource.url} title={field === "title" ? v.patch.after.title : d.page?.title} description={field === "meta_description" ? v.patch.after.meta_description : d.page?.meta_description} />
                </div>
                <div className="space-y-3">
                  <p className="text-[11.5px] uppercase tracking-wide text-fg-subtle">Validation</p>
                  {v.validation.passed ? <Badge tone="success"><Check className="size-3" /> Passed · {v.validation.length} chars</Badge> : <Badge tone="danger">Failed</Badge>}
                  {v.validation.errors?.map((e) => <p key={e} className="text-[12.5px] text-danger">✕ {e}</p>)}
                  {[...(v.validation.warnings ?? []), ...(v.patch.warnings ?? [])].map((w) => <p key={w} className="text-[12.5px] text-warning">! {w}</p>)}
                  {v.rationale && (
                    <div>
                      <p className="text-[11.5px] uppercase tracking-wide text-fg-subtle">Rationale</p>
                      <p className="mt-1 text-[13px] text-fg-muted">{v.rationale}</p>
                    </div>
                  )}
                  {v.evidence_ids.length > 0 && <p className="text-[11.5px] text-fg-subtle">Evidence: <span className="font-mono">{v.evidence_ids.join(", ")}</span></p>}
                </div>
              </div>
            </CardBody>
          </Card>

          {(latestApply || latestRollback) && (
            <Card>
              <CardHeader title="Execution & verification" />
              <CardBody className="space-y-4">
                {[latestApply, latestRollback].filter(Boolean).map((e) => <ExecutionPanel key={e!.id} e={e!} field={field} />)}
              </CardBody>
            </Card>
          )}

          <Card>
            <CardHeader title="Audit trail" description="Append-only and hash-chained." />
            <CardBody>
              {events.isLoading ? <Skeleton className="h-32" /> : (
                <Timeline
                  items={(events.data?.items ?? []).slice().reverse().map((e) => ({
                    id: e.id, at: e.created_at, title: e.action.replaceAll("_", " ").replace(".", " · "), actor: e.actor ?? e.actor_type, tone: TONE[e.action],
                    detail: e.data && Object.keys(e.data).length ? <span className="font-mono text-[11.5px]">{summarize(e.data)}</span> : undefined,
                  }))}
                />
              )}
            </CardBody>
          </Card>
        </div>

        <div className="space-y-5">
          <Card>
            <CardHeader title="Risk & policy" />
            <CardBody className="space-y-4">
              <RiskMeter score={d.risk_score} level={d.risk_level} />
              {d.policy_decision && (
                <>
                  <p className="text-[13px]">
                    Decision: <b>{d.policy_decision.decision === "auto_approve" ? "Auto-approved by Autopilot" : d.policy_decision.decision === "require_approval" ? "Human approval required" : "Denied"}</b>
                  </p>
                  <ul className="space-y-1.5">
                    {d.policy_decision.checks?.map((c) => (
                      <li key={c.name} className="flex gap-2 text-[12.5px]">
                        <span className={cn("mt-0.5 grid size-4 shrink-0 place-items-center rounded-full text-[10px] text-white", c.passed ? "bg-success" : "bg-fg-subtle")}>{c.passed ? "✓" : "–"}</span>
                        <span className={c.passed ? "text-fg-muted" : "text-fg"}>{c.detail}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <p className="text-[11.5px] text-fg-subtle">AI confidence is never a policy input. Approval binds to hash <span className="font-mono">{v.patch_hash.slice(0, 10)}…</span></p>
            </CardBody>
          </Card>
          {d.connector && (
            <Card>
              <CardHeader title="Connector" />
              <CardBody className="space-y-2 text-[13px]">
                <p className="capitalize">{d.connector.provider} <ConnectorModeBadge mode={d.connector.mode} /></p>
                <p className="text-fg-muted">Write mode: {d.connector.write_mode}</p>
                <p className="text-fg-muted">Resource version: <span className="font-mono">{v.resource_version ?? "n/a"}</span></p>
                {d.connector.rollback_supported ? <Badge tone="teal"><RotateCcw className="size-3" /> Rollback supported</Badge> : <Alert tone="warning" title="Rollback not guaranteed">Restoring requires human action.</Alert>}
                {d.rollback_note && <p className="text-[12px] text-fg-subtle">{d.rollback_note}</p>}
              </CardBody>
            </Card>
          )}
          <Card>
            <CardHeader title="Approvals" />
            <CardBody className="space-y-2">
              {d.approvals.length === 0 && <p className="text-[13px] text-fg-muted">None yet.</p>}
              {d.approvals.map((a) => {
                const stale = a.patch_version_id !== v.id;
                return (
                  <div key={a.id} className={cn("rounded-lg border border-border p-2.5 text-[12.5px]", stale && "opacity-60")}>
                    <div className="flex items-center justify-between">
                      <Badge tone={a.decision === "rejected" ? "danger" : "success"}>{a.decision.replace("_", " ")}</Badge>
                      <span className="text-fg-subtle">{fmtDate(a.created_at, true)}</span>
                    </div>
                    {a.reason && <p className="mt-1 text-fg-muted">“{a.reason}”</p>}
                    <p className="mt-1 font-mono text-[11px] text-fg-subtle">{a.patch_hash.slice(0, 16)}… {stale && "· superseded version"}</p>
                  </div>
                );
              })}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Versions" />
            <CardBody className="space-y-2">
              {d.versions.map((ver) => (
                <div key={ver.id} className={cn("rounded-lg border p-2.5 text-[12.5px]", ver.id === v.id ? "border-accent/40 bg-accent-soft/30" : "border-border")}>
                  <div className="flex justify-between"><b>v{ver.version}</b><span className="text-fg-subtle">{fmtDate(ver.created_at, true)}</span></div>
                  <p className="mt-1 line-clamp-2 text-fg-muted">{ver.patch.after[field]}</p>
                </div>
              ))}
            </CardBody>
          </Card>
        </div>
      </div>

      <ReasonDialog open={dialog === "approve"} title="Approve this version" description={`You are approving hash ${v.patch_hash.slice(0, 12)}… for ${pathOf(v.patch.resource.url)}. Any edit creates a new version that needs a new approval.`} cta="Approve" optional onClose={() => setDialog(null)} onSubmit={(r) => approve.mutate(r)} loading={approve.isPending} />
      <ReasonDialog open={dialog === "reject"} title="Reject change" description="A reason is required and is stored in the audit log." cta="Reject" danger onClose={() => setDialog(null)} onSubmit={(r) => reject.mutate(r)} loading={reject.isPending} />
      <ReasonDialog open={dialog === "rollback"} title="Roll back this change" description="Restores the value captured before the write, then re-checks the live page. If someone edited the field since, the rollback stops and asks for manual review." cta="Roll back" optional onClose={() => setDialog(null)} onSubmit={(r) => rollback.mutate(r)} loading={rollback.isPending} />
      <ReviseDialog open={dialog === "revise"} initial={v.patch.after[field] ?? ""} field={field} onClose={() => setDialog(null)} onSubmit={(val) => validate.mutate(val)} loading={validate.isPending} />
    </div>
  );
}

function summarize(data: Record<string, unknown>) {
  return Object.entries(data).filter(([, val]) => typeof val !== "object" || val === null).slice(0, 4).map(([k, val]) => `${k}=${String(val).slice(0, 40)}`).join(" · ");
}

function HashChip({ hash }: { hash: string }) {
  return (
    <button onClick={() => { navigator.clipboard.writeText(hash); toast.success("Patch hash copied"); }} className="inline-flex items-center gap-1 rounded-md border border-border bg-bg-subtle px-2 py-1 font-mono text-[11px] text-fg-muted hover:text-fg" aria-label="Copy patch hash">
      <Hash className="size-3" /> {hash.slice(0, 8)}…{hash.slice(-4)}
    </button>
  );
}

function ProgressBanner({ status }: { status: string }) {
  const steps = ["queued", "executing", "verifying", "completed"];
  const i = Math.max(0, steps.indexOf(status === "rollback_queued" ? "queued" : status));
  return (
    <Card className="mb-5 p-4">
      <div className="flex items-center gap-3">
        {steps.map((s, k) => (
          <React.Fragment key={s}>
            <div className="flex items-center gap-2">
              <span className={cn("grid size-6 place-items-center rounded-full text-[11px]", k < i ? "bg-success text-white" : k === i ? "bg-accent text-accent-fg" : "bg-bg-subtle text-fg-subtle")}>
                {k === i ? <motion.span animate={{ opacity: [1, 0.3, 1] }} transition={{ repeat: Infinity, duration: 1.2 }}>●</motion.span> : k < i ? "✓" : k + 1}
              </span>
              <span className="text-[13px] capitalize">{s === "executing" ? "writing" : s === "completed" ? "verified" : s}</span>
            </div>
            {k < steps.length - 1 && <span className="h-px flex-1 bg-border" />}
          </React.Fragment>
        ))}
      </div>
    </Card>
  );
}

function ExecutionPanel({ e, field }: { e: Execution; field: string }) {
  const ver: Verification = e.verification ?? {};
  const live = ver.observed?.live_html?.[field] ?? (ver.observed?.[field] as string | undefined);
  return (
    <div className="rounded-xl border border-border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13.5px] font-semibold capitalize">{e.kind === "rollback" ? "Rollback" : "Write"} · attempt {e.attempt}</p>
        <div className="flex items-center gap-2"><ConnectorModeBadge mode={e.connector_mode} /><StatusBadge status={e.status} /></div>
      </div>
      <p className="mt-1 text-[12px] text-fg-subtle">Started {fmtDate(e.started_at, true)} · finished {fmtDate(e.finished_at, true)}</p>
      {e.error && <p className="mt-2 text-[12.5px] text-danger">{e.error}</p>}
      {e.connector_result?.applied && <p className="mt-2 text-[12.5px] text-fg-muted">Connector accepted the write · new resource version <span className="font-mono">{e.connector_result.resource_version}</span></p>}
      {e.connector_result?.message && <p className="mt-2 text-[12.5px] text-fg-muted">{e.connector_result.message}</p>}
      {"verified" in ver && (
        <div className={cn("mt-3 rounded-lg p-3 text-[12.5px]", ver.verified ? "bg-success-soft" : ver.pending ? "bg-info-soft" : "bg-danger-soft")}>
          <p className="flex items-center gap-1.5 font-medium">
            <ShieldCheck className="size-4" /> {ver.verified ? "Verified in live HTML" : ver.pending ? "Stored — waiting for the live page to update" : "Not observed on the live page"}
          </p>
          <p className="mt-1 text-fg-muted">Method: {ver.method}{ver.details?.fetched_url && <> · fetched <span className="font-mono">{pathOf(ver.details.fetched_url)}</span></>}</p>
          {live !== undefined && <p className="mt-1 text-fg-muted">Observed: “{String(live ?? "")}”</p>}
        </div>
      )}
    </div>
  );
}

function ReasonDialog({ open, title, description, cta, danger, optional, onClose, onSubmit, loading }: { open: boolean; title: string; description: string; cta: string; danger?: boolean; optional?: boolean; onClose: () => void; onSubmit: (r: string) => void; loading: boolean }) {
  const [reason, setReason] = React.useState("");
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={title} description={description}>
        <form onSubmit={(e) => { e.preventDefault(); onSubmit(reason); }} className="space-y-4">
          <Field label={optional ? "Note (optional)" : "Reason"} htmlFor="reason">
            <Textarea id="reason" value={reason} onChange={(e) => setReason(e.target.value)} required={!optional} minLength={optional ? 0 : 3} />
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant={danger ? "danger" : "primary"} loading={loading}>{cta}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ReviseDialog({ open, initial, field, onClose, onSubmit, loading }: { open: boolean; initial: string; field: string; onClose: () => void; onSubmit: (v: string) => void; loading: boolean }) {
  const [value, setValue] = React.useState(initial);
  React.useEffect(() => { setValue(initial); }, [initial, open]);
  const [min, max] = field === "title" ? [30, 60] : [70, 160];
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="Revise the proposed value" description="Saving creates a new immutable version. Existing approvals will no longer apply.">
        <form onSubmit={(e) => { e.preventDefault(); onSubmit(value); }} className="space-y-3">
          <Textarea value={value} onChange={(e) => setValue(e.target.value)} aria-label="Proposed value" className="min-h-[120px]" />
          <p className={cn("text-[12px] tabular", value.length < min || value.length > max ? "text-warning" : "text-fg-subtle")}>{value.length} characters · recommended {min}–{max}</p>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" loading={loading} disabled={value.trim() === initial.trim()}>Save as new version</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
