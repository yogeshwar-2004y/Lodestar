"use client";

import { useMutation } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Bot, Info, SendHorizontal, Sparkles, User } from "lucide-react";
import { useParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { FixButton } from "@/components/app/fix-button";
import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, Textarea } from "@/components/ui/core";
import { ApiError, http } from "@/lib/api";
import { useMeta } from "@/lib/hooks";
import { pathOf } from "@/lib/utils";

type Answer = {
  answer: { answer: string; citations: string[]; proposed_actions: { action_type: string; url: string; value: string; rationale: string }[]; limitations: string[] };
  provider: string; model: string; fallback_used: boolean; note: string | null; credits_charged: number;
};
type Msg = { role: "user"; text: string } | { role: "assistant"; data: Answer };

const SUGGESTIONS = ["Which pages are missing meta descriptions?", "What should I fix first and why?", "Are there any indexability problems?", "Summarise broken links on the site"];

export default function Copilot() {
  const { siteId } = useParams<{ siteId: string }>();
  const meta = useMeta();
  const [msgs, setMsgs] = React.useState<Msg[]>([]);
  const [input, setInput] = React.useState("");
  const end = React.useRef<HTMLDivElement>(null);
  const ask = useMutation({
    mutationFn: (q: string) => http<Answer>("/copilot/messages", { json: { site_id: siteId, message: q } }),
    onSuccess: (data) => setMsgs((m) => [...m, { role: "assistant", data }]),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Copilot is unavailable"),
  });
  React.useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, ask.isPending]);
  const send = (q: string) => {
    if (!q.trim() || ask.isPending) return;
    setMsgs((m) => [...m, { role: "user", text: q }]);
    setInput("");
    ask.mutate(q);
  };
  return (
    <div className="mx-auto flex h-[calc(100dvh-120px)] max-w-4xl flex-col">
      <PageHeader
        title="AI Copilot"
        description="Answers only from this site's crawl evidence, Search Console data and change history — with citations."
        eyebrow={<Badge tone={meta.data?.ai_mode === "llm" ? "accent" : "warning"}>{meta.data?.ai_mode === "llm" ? meta.data.ai_model : "Deterministic mode (no AI model configured)"}</Badge>}
      />
      <Card className="flex min-h-0 flex-1 flex-col">
        <div className="flex-1 space-y-5 overflow-y-auto p-5" aria-live="polite">
          {msgs.length === 0 && (
            <div className="grid h-full place-items-center text-center">
              <div>
                <span className="mx-auto grid size-12 place-items-center rounded-2xl bg-gradient-to-br from-accent to-teal text-white"><Sparkles className="size-5" /></span>
                <p className="mt-3 font-medium">Ask about this site</p>
                <p className="mt-1 text-[13px] text-fg-muted">The Copilot can&apos;t browse the web or change anything — it proposes actions you review.</p>
                <div className="mt-5 flex flex-wrap justify-center gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} onClick={() => send(s)} className="rounded-full border border-border bg-surface px-3 py-1.5 text-[12.5px] text-fg-muted hover:border-border-strong hover:text-fg">{s}</button>
                  ))}
                </div>
              </div>
            </div>
          )}
          <AnimatePresence initial={false}>
            {msgs.map((m, i) => (
              <motion.div key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3">
                <span className={`grid size-8 shrink-0 place-items-center rounded-full ${m.role === "user" ? "bg-bg-subtle" : "bg-accent text-accent-fg"}`}>
                  {m.role === "user" ? <User className="size-4" /> : <Bot className="size-4" />}
                </span>
                <div className="min-w-0 flex-1">
                  {m.role === "user" ? <p className="pt-1 text-[14px]">{m.text}</p> : <AnswerView a={m.data} siteId={siteId} />}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
          {ask.isPending && (
            <div className="flex gap-3">
              <span className="grid size-8 place-items-center rounded-full bg-accent text-accent-fg"><Bot className="size-4" /></span>
              <div className="flex gap-1 pt-3" aria-label="Thinking">{[0, 1, 2].map((k) => <motion.span key={k} className="size-1.5 rounded-full bg-fg-subtle" animate={{ opacity: [0.2, 1, 0.2] }} transition={{ repeat: Infinity, duration: 1, delay: k * 0.15 }} />)}</div>
            </div>
          )}
          <div ref={end} />
        </div>
        <form onSubmit={(e) => { e.preventDefault(); send(input); }} className="flex items-end gap-2 border-t border-border p-3">
          <Textarea
            aria-label="Ask the Copilot"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
            placeholder="Ask about issues, pages or priorities… (Enter to send)"
            className="min-h-[44px] resize-none"
            maxLength={2000}
          />
          <Button type="submit" size="icon" aria-label="Send" loading={ask.isPending}><SendHorizontal /></Button>
        </form>
      </Card>
    </div>
  );
}

function AnswerView({ a, siteId }: { a: Answer; siteId: string }) {
  return (
    <div className="space-y-3">
      <div className="whitespace-pre-wrap text-[14px] leading-relaxed">{a.answer.answer}</div>
      {a.answer.citations.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {a.answer.citations.slice(0, 10).map((c) => <Badge key={c} tone="neutral"><span className="font-mono text-[10.5px]">{c.split(":")[0]}:{c.split(":")[1]?.slice(0, 6)}</span></Badge>)}
        </div>
      )}
      {a.answer.proposed_actions.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {a.answer.proposed_actions.map((p) => (
            <div key={p.url + p.action_type} className="rounded-xl border border-accent/25 bg-accent-soft/40 p-3">
              <p className="text-[12px] font-medium uppercase tracking-wide text-accent">Proposed action</p>
              <p className="mt-1 text-[13px]">{p.action_type.replace("_", " ")} · <span className="font-mono">{pathOf(p.url)}</span></p>
              <p className="mt-1 text-[12.5px] text-fg-muted">{p.rationale}</p>
              <div className="mt-2"><FixButton siteId={siteId} url={p.url} action={p.action_type} label="Draft for review" /></div>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-start gap-1.5 text-[11.5px] text-fg-subtle">
        <Info className="mt-0.5 size-3.5 shrink-0" />
        <span>{[...a.answer.limitations, a.note].filter(Boolean).join(" ")} {a.credits_charged ? `· ${a.credits_charged} credits` : ""}</span>
      </div>
    </div>
  );
}
