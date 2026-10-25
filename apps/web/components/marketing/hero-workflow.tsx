"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { CheckCircle2, FileSearch, ShieldCheck, Sparkles } from "lucide-react";
import * as React from "react";

const STAGES = ["finding", "draft", "approval", "verified"] as const;

/** Illustrative walkthrough of the fix workflow (example content, not customer data). */
export function HeroWorkflow() {
  const reduce = useReducedMotion();
  const [i, setI] = React.useState(0);
  React.useEffect(() => {
    if (reduce) return;
    const t = setInterval(() => setI((x) => (x + 1) % STAGES.length), 2600);
    return () => clearInterval(t);
  }, [reduce]);
  const stage = STAGES[i];
  return (
    <div className="relative" aria-label="Illustration of the fix workflow">
      <div className="absolute -inset-4 rounded-[28px] bg-gradient-to-br from-accent/15 to-teal/10 blur-2xl" aria-hidden />
      <div className="relative rounded-[22px] border border-border bg-surface p-5 shadow-2xl">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5" aria-hidden>
            <span className="size-2.5 rounded-full bg-danger/60" />
            <span className="size-2.5 rounded-full bg-warning/60" />
            <span className="size-2.5 rounded-full bg-success/60" />
          </div>
          <span className="rounded-full bg-bg-subtle px-2 py-0.5 text-[10.5px] text-fg-subtle">Example</span>
        </div>
        <div className="mt-4 flex gap-1.5" aria-hidden>
          {STAGES.map((s, k) => (
            <div key={s} className={`h-1 flex-1 rounded-full transition-colors duration-500 ${k <= i ? "bg-accent" : "bg-bg-subtle"}`} />
          ))}
        </div>
        <div className="mt-5 min-h-[248px]">
          <AnimatePresence mode="wait">
            <motion.div key={stage} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.3 }}>
              {stage === "finding" && (
                <Panel icon={FileSearch} label="Audit finding" tone="text-warning">
                  <p className="text-[15px] font-semibold">Missing meta description</p>
                  <p className="mt-1 text-[13px] text-fg-muted">/subscriptions/ · deterministic · medium severity</p>
                  <pre className="mt-3 overflow-hidden rounded-lg bg-bg-subtle p-3 font-mono text-[11.5px] text-fg-muted">{`<head>\n  <title>Coffee subscriptions</title>\n  <!-- no meta description -->\n</head>`}</pre>
                </Panel>
              )}
              {stage === "draft" && (
                <Panel icon={Sparkles} label="Proposed patch v1" tone="text-accent">
                  <p className="text-[12px] uppercase tracking-wide text-fg-subtle">After</p>
                  <p className="mt-1 rounded-lg bg-success-soft p-3 text-[13.5px] leading-relaxed text-success">
                    Choose a roast, pick a schedule, pause anytime. Beans ship within 48 hours of roasting.
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2 text-[11.5px]">
                    <span className="rounded-full bg-bg-subtle px-2 py-0.5">Validation passed</span>
                    <span className="rounded-full bg-bg-subtle px-2 py-0.5">Risk low · 0.15</span>
                    <span className="rounded-full bg-bg-subtle px-2 py-0.5 font-mono">sha256 9f2c…a71e</span>
                  </div>
                </Panel>
              )}
              {stage === "approval" && (
                <Panel icon={ShieldCheck} label="Approval inbox" tone="text-teal">
                  <p className="text-[14px]">Policy: <b>Assist mode</b> — human approval required.</p>
                  <div className="mt-4 flex gap-2">
                    <span className="rounded-lg bg-accent px-3 py-1.5 text-[13px] font-medium text-accent-fg">Approve hash 9f2c…a71e</span>
                    <span className="rounded-lg border border-border px-3 py-1.5 text-[13px]">Reject</span>
                  </div>
                  <p className="mt-3 text-[12px] text-fg-subtle">Editing the text creates v2 and invalidates this approval.</p>
                </Panel>
              )}
              {stage === "verified" && (
                <Panel icon={CheckCircle2} label="Live verification" tone="text-success">
                  <p className="text-[15px] font-semibold">Written via WordPress plugin · verified in live HTML</p>
                  <pre className="mt-3 overflow-hidden whitespace-pre-wrap rounded-lg bg-bg-subtle p-3 font-mono text-[11.5px] text-fg-muted">{`<meta name="description"\n  content="Choose a roast, pick a schedule…">`}</pre>
                  <p className="mt-3 text-[12px] text-fg-subtle">Previous value snapshotted · rollback available</p>
                </Panel>
              )}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

function Panel({ icon: Icon, label, tone, children }: { icon: React.ComponentType<{ className?: string }>; label: string; tone: string; children: React.ReactNode }) {
  return (
    <div>
      <div className={`mb-3 flex items-center gap-2 text-[12px] font-medium uppercase tracking-wide ${tone}`}>
        <Icon className="size-4" aria-hidden /> {label}
      </div>
      {children}
    </div>
  );
}
