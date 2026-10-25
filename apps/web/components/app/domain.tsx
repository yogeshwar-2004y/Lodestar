"use client";

import { motion } from "framer-motion";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge, type Tone } from "@/components/ui/core";
import { cn, fmtDate } from "@/lib/utils";

/* ------------------------------------------------------------------ badges */

const SEV_TONE: Record<string, Tone> = { critical: "danger", high: "danger", medium: "warning", low: "info", info: "neutral" };
export function SeverityBadge({ severity }: { severity: string }) {
  return (
    <Badge tone={SEV_TONE[severity] ?? "neutral"} dot>
      {severity}
    </Badge>
  );
}

export function KindBadge({ kind }: { kind: string }) {
  return kind === "deterministic" ? <Badge tone="accent">Deterministic</Badge> : <Badge tone="teal">Heuristic</Badge>;
}

const STATUS: Record<string, { tone: Tone; label: string }> = {
  draft: { tone: "neutral", label: "Draft" },
  recommendation: { tone: "neutral", label: "Recommendation only" },
  invalid: { tone: "danger", label: "Failed validation" },
  blocked: { tone: "danger", label: "Blocked by policy" },
  pending_approval: { tone: "warning", label: "Approval pending" },
  approved: { tone: "accent", label: "Approved" },
  rejected: { tone: "neutral", label: "Rejected" },
  queued: { tone: "info", label: "Queued" },
  executing: { tone: "info", label: "Writing" },
  verifying: { tone: "info", label: "Verifying live" },
  awaiting_deploy: { tone: "info", label: "Awaiting deploy" },
  completed: { tone: "success", label: "Verified live" },
  failed: { tone: "danger", label: "Execution failed" },
  verification_failed: { tone: "danger", label: "Not verified" },
  rollback_queued: { tone: "info", label: "Rollback queued" },
  rolled_back: { tone: "teal", label: "Rolled back" },
  rollback_failed: { tone: "danger", label: "Rollback needs action" },
  cancelled: { tone: "neutral", label: "Cancelled" },
  succeeded: { tone: "success", label: "Succeeded" },
  running: { tone: "info", label: "Running" },
  dead_letter: { tone: "danger", label: "Dead-lettered" },
};
export function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { tone: "neutral" as Tone, label: status.replaceAll("_", " ") };
  return (
    <Badge tone={s.tone} dot>
      {s.label}
    </Badge>
  );
}

export function RiskMeter({ score, level }: { score?: number | null; level?: string | null }) {
  if (score === null || score === undefined) return <span className="text-fg-subtle">—</span>;
  const tone = level === "high" ? "bg-danger" : level === "medium" ? "bg-warning" : "bg-success";
  return (
    <div className="flex items-center gap-2" aria-label={`Risk ${level} (${score})`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-bg-subtle">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${Math.max(6, score * 100)}%` }} />
      </div>
      <span className="text-xs capitalize text-fg-muted tabular">
        {level} · {score.toFixed(2)}
      </span>
    </div>
  );
}

export function ConnectorModeBadge({ mode }: { mode?: string | null }) {
  if (!mode) return null;
  return mode === "fixture" ? <Badge tone="warning">Fixture connector</Badge> : <Badge tone="success">Live connector</Badge>;
}

/* ------------------------------------------------------------------ health ring */

export function HealthRing({ score, size = 132 }: { score: number | null | undefined; size?: number }) {
  const r = (size - 14) / 2;
  const c = 2 * Math.PI * r;
  const v = score ?? 0;
  const color = score === null || score === undefined ? "var(--border-strong)" : v >= 85 ? "var(--success)" : v >= 65 ? "var(--warning)" : "var(--danger)";
  return (
    <div className="relative" style={{ width: size, height: size }} role="img" aria-label={`Internal health score ${score ?? "not available"}`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--bg-subtle)" strokeWidth={10} fill="none" />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={color}
          strokeWidth={10}
          strokeLinecap="round"
          fill="none"
          strokeDasharray={c}
          initial={{ strokeDashoffset: c }}
          animate={{ strokeDashoffset: c - (c * v) / 100 }}
          transition={{ duration: 0.9, ease: [0.2, 0.8, 0.2, 1] }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <div className="font-display text-4xl leading-none tabular">{score ?? "—"}</div>
          <div className="mt-1 text-[10.5px] uppercase tracking-wider text-fg-subtle">internal score</div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ diff */

function wordDiff(a: string, b: string): { text: string; type: "same" | "add" | "del" }[] {
  const A = a.split(/(\s+)/);
  const B = b.split(/(\s+)/);
  const dp = Array.from({ length: A.length + 1 }, () => new Array<number>(B.length + 1).fill(0));
  for (let i = A.length - 1; i >= 0; i--) for (let j = B.length - 1; j >= 0; j--) dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: { text: string; type: "same" | "add" | "del" }[] = [];
  let i = 0;
  let j = 0;
  while (i < A.length && j < B.length) {
    if (A[i] === B[j]) {
      out.push({ text: A[i], type: "same" });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ text: A[i++], type: "del" });
    else out.push({ text: B[j++], type: "add" });
  }
  while (i < A.length) out.push({ text: A[i++], type: "del" });
  while (j < B.length) out.push({ text: B[j++], type: "add" });
  return out;
}

export function DiffView({ field, before, after }: { field: string; before: string; after: string }) {
  const parts = wordDiff(before ?? "", after ?? "");
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div className="rounded-[10px] border border-border bg-surface-2">
        <div className="flex items-center justify-between border-b border-border px-3 py-2 text-[11.5px] uppercase tracking-wide text-fg-subtle">
          <span>Before</span>
          <span className="font-mono normal-case">{field}</span>
        </div>
        <p className="min-h-[64px] p-3 text-[13.5px] leading-relaxed">
          {before ? (
            parts.filter((p) => p.type !== "add").map((p, k) => (
              <span key={k} className={p.type === "del" ? "rounded bg-danger-soft text-danger line-through decoration-danger/50" : ""}>
                {p.text}
              </span>
            ))
          ) : (
            <span className="italic text-fg-subtle">(empty — tag not present)</span>
          )}
        </p>
        <div className="border-t border-border px-3 py-1.5 text-[11px] text-fg-subtle tabular">{(before ?? "").length} chars</div>
      </div>
      <div className="rounded-[10px] border border-accent/30 bg-accent-soft/40">
        <div className="flex items-center justify-between border-b border-accent/20 px-3 py-2 text-[11.5px] uppercase tracking-wide text-accent">
          <span>After</span>
          <span className="font-mono normal-case">{field}</span>
        </div>
        <p className="min-h-[64px] p-3 text-[13.5px] leading-relaxed">
          {parts.filter((p) => p.type !== "del").map((p, k) => (
            <span key={k} className={p.type === "add" ? "rounded bg-success-soft text-success" : ""}>
              {p.text}
            </span>
          ))}
        </p>
        <div className="border-t border-accent/20 px-3 py-1.5 text-[11px] text-fg-subtle tabular">{(after ?? "").length} chars</div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ SERP preview */

export function SerpPreview({ url, title, description }: { url: string; title?: string | null; description?: string | null }) {
  return (
    <div className="rounded-[10px] border border-border bg-surface p-4" aria-label="Search snippet preview (approximate)">
      <div className="truncate text-[12px] text-fg-muted">{url}</div>
      <div className="mt-0.5 line-clamp-1 text-[17px] text-[#1a0dab] dark:text-[#8ab4f8]">{title || "(no title)"}</div>
      <div className="mt-1 line-clamp-2 text-[13px] text-fg-muted">{description || <span className="italic">No meta description — search engines will pick text from the page.</span>}</div>
      <div className="mt-2 text-[10.5px] text-fg-subtle">Approximate preview. Search engines may rewrite snippets.</div>
    </div>
  );
}

/* ------------------------------------------------------------------ timeline */

export type TimelineItem = { id: string; at: string; title: string; actor?: string | null; detail?: React.ReactNode; tone?: Tone };
export function Timeline({ items }: { items: TimelineItem[] }) {
  return (
    <ol className="relative space-y-4 pl-6">
      <span className="absolute left-[7px] top-1 bottom-1 w-px bg-border" aria-hidden />
      {items.map((it) => (
        <li key={it.id} className="relative">
          <span
            className={cn(
              "absolute -left-6 top-1 size-[15px] rounded-full border-2 border-surface",
              it.tone === "success" ? "bg-success" : it.tone === "danger" ? "bg-danger" : it.tone === "warning" ? "bg-warning" : it.tone === "teal" ? "bg-teal" : "bg-accent",
            )}
            aria-hidden
          />
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-[13px] font-medium">{it.title}</span>
            <span className="text-[11.5px] text-fg-subtle">{fmtDate(it.at, true)}</span>
            {it.actor && <span className="text-[11.5px] text-fg-subtle">· {it.actor}</span>}
          </div>
          {it.detail && <div className="mt-1 text-[12.5px] text-fg-muted">{it.detail}</div>}
        </li>
      ))}
    </ol>
  );
}

/* ------------------------------------------------------------------ charts */

const tooltipStyle = { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12, color: "var(--fg)" };

export function TrendChart({ data, dataKey, height = 220, annotations = [], color = "var(--accent)" }: { data: Record<string, unknown>[]; dataKey: string; height?: number; annotations?: { date: string; title: string }[]; color?: string }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
        <defs>
          <linearGradient id={`g-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.22} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="date" tick={{ fontSize: 11, fill: "var(--fg-subtle)" }} tickLine={false} axisLine={false} minTickGap={32} />
        <YAxis tick={{ fontSize: 11, fill: "var(--fg-subtle)" }} tickLine={false} axisLine={false} width={44} />
        <RTooltip contentStyle={tooltipStyle} />
        {annotations.map((a) => (
          <ReferenceLine key={a.date + a.title} x={a.date} stroke="var(--teal)" strokeDasharray="4 3" label={{ value: "◆", fill: "var(--teal)", fontSize: 10, position: "top" }} />
        ))}
        <Area type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} fill={`url(#g-${dataKey})`} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function Sparkline({ data, dataKey, color = "var(--accent)" }: { data: Record<string, unknown>[]; dataKey: string; color?: string }) {
  if (data.length < 2) return <div className="h-8 text-[11px] text-fg-subtle">Not enough history</div>;
  return (
    <ResponsiveContainer width="100%" height={36}>
      <LineChart data={data}>
        <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function SeverityBars({ data }: { data: Record<string, number> }) {
  const rows = ["critical", "high", "medium", "low", "info"].map((k) => ({ k, v: data[k] ?? 0 }));
  const max = Math.max(1, ...rows.map((r) => r.v));
  const color: Record<string, string> = { critical: "bg-danger", high: "bg-danger/70", medium: "bg-warning", low: "bg-info", info: "bg-border-strong" };
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.k} className="flex items-center gap-3 text-[12.5px]">
          <span className="w-16 capitalize text-fg-muted">{r.k}</span>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-bg-subtle">
            <motion.div className={cn("h-full rounded-full", color[r.k])} initial={{ width: 0 }} animate={{ width: `${(r.v / max) * 100}%` }} transition={{ duration: 0.6 }} />
          </div>
          <span className="w-8 text-right tabular">{r.v}</span>
        </div>
      ))}
    </div>
  );
}

export function CategoryBars({ data }: { data: { name: string; value: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} layout="vertical" margin={{ left: 20, right: 12 }}>
        <XAxis type="number" domain={[0, 100]} hide />
        <YAxis type="category" dataKey="name" tick={{ fontSize: 11.5, fill: "var(--fg-muted)" }} width={110} axisLine={false} tickLine={false} />
        <RTooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--bg-subtle)" }} />
        <Bar dataKey="value" fill="var(--teal)" radius={[0, 6, 6, 0]} barSize={12} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function StatCard({ label, value, hint, children }: { label: string; value: React.ReactNode; hint?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="rounded-[var(--radius)] border border-border bg-surface p-4 shadow-card">
      <div className="text-[12px] font-medium text-fg-subtle">{label}</div>
      <div className="mt-1 font-display text-[30px] leading-tight tabular">{value}</div>
      {hint && <div className="mt-0.5 text-[12px] text-fg-muted">{hint}</div>}
      {children}
    </div>
  );
}
