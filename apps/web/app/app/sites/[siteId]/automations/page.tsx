"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Hand, OctagonX, Pause, Play, Rocket } from "lucide-react";
import { useParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { StatusBadge } from "@/components/app/domain";
import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, CardBody, CardHeader, Field, Input, NativeSelect, Skeleton, Switch } from "@/components/ui/core";
import { ApiError, http } from "@/lib/api";
import { useCan, useSession } from "@/lib/hooks";
import { cn, fmtDate, timeAgo } from "@/lib/utils";

type Auto = {
  policy: { mode: string; auto_actions: string[]; path_scope: string[]; paused: boolean; max_auto_changes_per_day: number; max_risk_score: number; updated_at: string };
  kill_switch: boolean;
  schedules: { id: string; kind: string; interval_minutes: number; enabled: boolean; next_run_at: string | null; last_run_at: string | null }[];
  event_triggers: { event: string; action: string; enabled: boolean }[];
  auto_eligible_actions: string[]; always_review: string[]; restricted: string[];
};
type Workflow = { id: string; kind: string; status: string; trigger: string; created_at: string; steps: { name: string; status: string; error?: string }[]; agent_runs: { id: string; agent: string; task: string; provider: string; model: string; input_tokens: number; output_tokens: number; cost_usd: number; credits: number; latency_ms: number | null }[] };

const MODES = [
  { key: "observe", icon: Eye, title: "Observe", body: "Monitor and recommend. No writes at all." },
  { key: "assist", icon: Hand, title: "Assist", body: "Agents draft fixes; every write needs human approval. Default." },
  { key: "autopilot", icon: Rocket, title: "Autopilot", body: "Whitelisted low-risk metadata in chosen paths may run automatically — within limits." },
];

export default function Automations() {
  const { siteId } = useParams<{ siteId: string }>();
  const qc = useQueryClient();
  const canManage = useCan("automation:manage");
  const canKill = useCan("killswitch:toggle");
  const session = useSession();
  const q = useQuery({ queryKey: ["automations", siteId], queryFn: () => http<Auto>(`/sites/${siteId}/automations`) });
  const runs = useQuery({ queryKey: ["workflows", siteId], queryFn: () => http<Workflow[]>(`/sites/${siteId}/workflows`), refetchInterval: 10_000 });
  const [form, setForm] = React.useState<Auto["policy"] | null>(null);
  React.useEffect(() => { if (q.data) setForm(q.data.policy); }, [q.data]);
  const save = useMutation({
    mutationFn: (p: Auto["policy"]) => http<Auto>(`/sites/${siteId}/automations/policy`, { method: "PUT", json: { mode: p.mode, auto_actions: p.auto_actions, path_scope: p.path_scope, max_auto_changes_per_day: p.max_auto_changes_per_day, max_risk_score: p.max_risk_score, paused: p.paused } }),
    onSuccess: (d) => { qc.setQueryData(["automations", siteId], d); toast.success("Policy saved"); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  const schedule = useMutation({
    mutationFn: (v: { interval_minutes: number; enabled: boolean }) => http<Auto>(`/sites/${siteId}/automations/schedule`, { method: "PUT", json: { kind: "crawl", ...v } }),
    onSuccess: (d) => { qc.setQueryData(["automations", siteId], d); toast.success("Schedule saved"); },
  });
  const kill = useMutation({
    mutationFn: (engaged: boolean) => http<{ kill_switch: boolean; cancelled_executions: number }>(`/organizations/current/kill-switch?engaged=${engaged}`, { method: "POST" }),
    onSuccess: (r) => { qc.invalidateQueries(); toast[r.kill_switch ? "error" : "success"](r.kill_switch ? `Kill switch engaged · ${r.cancelled_executions} queued executions cancelled` : "Kill switch released"); },
  });
  if (!q.data || !form) return <Skeleton className="h-96" />;
  const crawlSchedule = q.data.schedules.find((s) => s.kind === "crawl");
  const dirty = JSON.stringify(form) !== JSON.stringify(q.data.policy);
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Automation center"
        description="Decide how much the agents may do on their own. Policy is enforced server-side on every write."
        actions={canKill && (
          <Button variant={q.data.kill_switch ? "secondary" : "danger"} onClick={() => kill.mutate(!q.data!.kill_switch)} loading={kill.isPending}>
            <OctagonX /> {q.data.kill_switch ? "Release kill switch" : "Emergency kill switch"}
          </Button>
        )}
      />
      {q.data.kill_switch && <Alert tone="danger" className="mb-5" title="Kill switch engaged">All executions across {session.data?.organization?.name} are blocked and queued work was cancelled.</Alert>}
      <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
        <div className="space-y-5">
          <Card>
            <CardHeader title="Policy mode" action={<Button size="sm" variant={form.paused ? "secondary" : "ghost"} disabled={!canManage} onClick={() => setForm({ ...form, paused: !form.paused })}>{form.paused ? <><Play /> Resume</> : <><Pause /> Pause automation</>}</Button>} />
            <CardBody className="space-y-5">
              <div role="radiogroup" aria-label="Policy mode" className="grid gap-3 md:grid-cols-3">
                {MODES.map((m) => (
                  <button key={m.key} role="radio" aria-checked={form.mode === m.key} disabled={!canManage} onClick={() => setForm({ ...form, mode: m.key })} className={cn("rounded-xl border p-4 text-left transition-colors disabled:cursor-not-allowed", form.mode === m.key ? "border-accent bg-accent-soft/40 ring-1 ring-accent/30" : "border-border hover:border-border-strong")}>
                    <m.icon className="size-5 text-accent" />
                    <p className="mt-2 font-semibold">{m.title}</p>
                    <p className="mt-0.5 text-[12.5px] text-fg-muted">{m.body}</p>
                  </button>
                ))}
              </div>
              {form.paused && <Alert tone="warning" title="Paused">Scheduled crawls and automatic proposals are paused for this site.</Alert>}
              {form.mode === "autopilot" && (
                <div className="space-y-4 rounded-xl border border-border p-4">
                  <p className="text-[13px] font-semibold">Autopilot limits</p>
                  <div className="flex flex-wrap gap-4">
                    {q.data.auto_eligible_actions.map((a) => (
                      <label key={a} className="flex items-center gap-2 text-[13px]">
                        <Switch checked={form.auto_actions.includes(a)} disabled={!canManage} label={`Auto-execute ${a}`} onCheckedChange={(v) => setForm({ ...form, auto_actions: v ? [...form.auto_actions, a] : form.auto_actions.filter((x) => x !== a) })} />
                        <span className="font-mono">{a}</span>
                      </label>
                    ))}
                  </div>
                  <div className="grid gap-4 sm:grid-cols-3">
                    <Field label="Path scope" htmlFor="scope" hint="Comma-separated prefixes. Empty = whole site.">
                      <Input id="scope" disabled={!canManage} value={form.path_scope.join(", ")} onChange={(e) => setForm({ ...form, path_scope: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
                    </Field>
                    <Field label="Max auto-changes / day" htmlFor="max"><Input id="max" type="number" min={0} max={500} disabled={!canManage} value={form.max_auto_changes_per_day} onChange={(e) => setForm({ ...form, max_auto_changes_per_day: Number(e.target.value) })} /></Field>
                    <Field label="Max risk score" htmlFor="risk" hint="0–1. Homepage changes score higher."><Input id="risk" type="number" min={0} max={1} step={0.05} disabled={!canManage} value={form.max_risk_score} onChange={(e) => setForm({ ...form, max_risk_score: Number(e.target.value) })} /></Field>
                  </div>
                </div>
              )}
              <div className="flex flex-wrap gap-2 text-[12px]">
                <span className="text-fg-subtle">Always reviewed:</span>{q.data.always_review.map((a) => <Badge key={a}>{a}</Badge>)}
                <span className="ml-2 text-fg-subtle">Never automated:</span>{q.data.restricted.map((a) => <Badge key={a} tone="danger">{a}</Badge>)}
              </div>
              {canManage && <Button onClick={() => save.mutate(form)} disabled={!dirty} loading={save.isPending}>Save policy</Button>}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Recent runs" description="Persisted agent workflows with model, tokens and cost." />
            <CardBody className="space-y-3">
              {runs.data?.length === 0 && <p className="text-[13px] text-fg-muted">No runs yet.</p>}
              {runs.data?.slice(0, 10).map((w) => (
                <details key={w.id} className="rounded-xl border border-border">
                  <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 px-4 py-3">
                    <span className="text-[13.5px] font-medium capitalize">{w.kind.replaceAll("_", " ")} <span className="font-normal text-fg-subtle">· {w.trigger} · {timeAgo(w.created_at)}</span></span>
                    <StatusBadge status={w.status === "completed" ? "succeeded" : w.status} />
                  </summary>
                  <div className="border-t border-border px-4 py-3 text-[12.5px]">
                    <p className="text-fg-muted">{w.steps.map((s) => `${s.name}: ${s.status}${s.error ? ` (${s.error})` : ""}`).join(" → ")}</p>
                    <ul className="mt-2 space-y-1">
                      {w.agent_runs.map((r) => (
                        <li key={r.id} className="flex flex-wrap justify-between gap-2 rounded-md bg-bg-subtle px-2.5 py-1.5 font-mono text-[11.5px]">
                          <span>{r.agent}/{r.task}</span>
                          <span className="text-fg-muted">{r.provider === "deterministic" ? "deterministic" : r.model} · {r.input_tokens + r.output_tokens} tok · ${r.cost_usd.toFixed(4)} · {r.credits} cr · {r.latency_ms ?? 0}ms</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </details>
              ))}
            </CardBody>
          </Card>
        </div>
        <div className="space-y-5">
          <Card>
            <CardHeader title="Scheduled crawl" />
            <CardBody className="space-y-3 text-[13px]">
              <ScheduleForm initial={crawlSchedule} disabled={!canManage} onSave={(v) => schedule.mutate(v)} />
              <p className="text-fg-subtle">Next: {fmtDate(crawlSchedule?.next_run_at, true)} · Last: {fmtDate(crawlSchedule?.last_run_at, true)}</p>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Event triggers" />
            <CardBody className="space-y-2">
              {q.data.event_triggers.map((t) => (
                <div key={t.event} className="rounded-lg border border-border p-2.5 text-[12.5px]">
                  <p className="font-medium">{t.event}</p>
                  <p className="text-fg-muted">→ {t.action}</p>
                </div>
              ))}
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}

function ScheduleForm({ initial, disabled, onSave }: { initial?: { interval_minutes: number; enabled: boolean }; disabled: boolean; onSave: (v: { interval_minutes: number; enabled: boolean }) => void }) {
  const [interval, setInterval] = React.useState(initial?.interval_minutes ?? 10080);
  const [enabled, setEnabled] = React.useState(initial?.enabled ?? true);
  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2"><Switch checked={enabled} onCheckedChange={setEnabled} disabled={disabled} label="Enable scheduled crawl" /> Enabled</label>
      <NativeSelect aria-label="Frequency" value={interval} onChange={(e) => setInterval(Number(e.target.value))} disabled={disabled} className="w-full">
        <option value={1440}>Daily</option>
        <option value={4320}>Every 3 days</option>
        <option value={10080}>Weekly</option>
        <option value={43200}>Monthly</option>
      </NativeSelect>
      <Button size="sm" variant="secondary" disabled={disabled} onClick={() => onSave({ interval_minutes: interval, enabled })}>Save schedule</Button>
    </div>
  );
}
