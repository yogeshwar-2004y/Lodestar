"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpenText, Check, Save, Send, X } from "lucide-react";
import { useParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { StatusBadge } from "@/components/app/domain";
import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, CardBody, CardHeader, EmptyState, Field, Input, Textarea } from "@/components/ui/core";
import { ApiError, http } from "@/lib/api";
import { useCan } from "@/lib/hooks";
import { cn, timeAgo } from "@/lib/utils";

type Draft = { id: string; title: string; target_query: string; brief: { search_intent?: string; outline?: string[]; key_points?: string[]; internal_link_suggestions?: string[]; sources_needed?: string[]; caveats?: string[] }; body: string; status: string; review_notes: string | null; ai_generated: boolean; updated_at: string; publishing: string };

const STATUS_MAP: Record<string, string> = { draft: "draft", in_review: "pending_approval", approved: "approved", rejected: "rejected" };

export default function ContentStudio() {
  const { siteId } = useParams<{ siteId: string }>();
  const qc = useQueryClient();
  const canWrite = useCan("content:write");
  const canApprove = useCan("content:approve");
  const drafts = useQuery({ queryKey: ["drafts", siteId], queryFn: () => http<Draft[]>(`/sites/${siteId}/content/drafts`) });
  const [selected, setSelected] = React.useState<string | null>(null);
  const current = drafts.data?.find((d) => d.id === selected) ?? drafts.data?.[0];
  const [body, setBody] = React.useState("");
  const [notes, setNotes] = React.useState("");
  React.useEffect(() => { setBody(current?.body ?? ""); setNotes(""); }, [current?.id, current?.body]);
  const create = useMutation({
    mutationFn: (v: { target_query: string; notes: string }) => http<Draft>(`/sites/${siteId}/content/drafts`, { json: v }),
    onSuccess: (d) => { qc.invalidateQueries({ queryKey: ["drafts", siteId] }); setSelected(d.id); toast.success("Brief and draft created"); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  const act = useMutation({
    mutationFn: (action: string) => http<Draft>(`/content/drafts/${current!.id}/${action}`, { json: { body: action === "save" || action === "submit" ? body : undefined, notes: notes || undefined } }),
    onSuccess: (_, a) => { qc.invalidateQueries({ queryKey: ["drafts", siteId] }); toast.success({ save: "Saved", submit: "Sent for editorial review", approve: "Editorially approved", reject: "Returned to writer" }[a] ?? "Done"); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  const editable = current && ["draft", "rejected"].includes(current.status) && canWrite;
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Content Studio" description="Briefs and first drafts for your editors. Drafts are never published automatically — approval here is editorial sign-off, publishing is manual." />
      <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
        <div className="space-y-4">
          {canWrite && (
            <Card>
              <CardHeader title="New brief" />
              <CardBody>
                <form onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); create.mutate({ target_query: String(f.get("q")), notes: String(f.get("notes") ?? "") }); e.currentTarget.reset(); }} className="space-y-3">
                  <Field label="Target query" htmlFor="q"><Input id="q" name="q" required minLength={2} placeholder="how to brew pour over coffee" /></Field>
                  <Field label="Notes for the writer" htmlFor="notes"><Textarea id="notes" name="notes" className="min-h-[64px]" /></Field>
                  <Button type="submit" className="w-full" loading={create.isPending}>Create brief</Button>
                </form>
              </CardBody>
            </Card>
          )}
          <Card>
            <CardHeader title="Review queue" />
            <ul className="divide-y divide-border">
              {drafts.data?.length === 0 && <li className="px-5 pb-4 text-[13px] text-fg-muted">No drafts yet.</li>}
              {drafts.data?.map((d) => (
                <li key={d.id}>
                  <button onClick={() => setSelected(d.id)} className={cn("w-full px-5 py-3 text-left hover:bg-bg-subtle", current?.id === d.id && "bg-accent-soft/40")}>
                    <p className="truncate text-[13.5px] font-medium">{d.title}</p>
                    <div className="mt-1 flex items-center gap-2"><StatusBadge status={STATUS_MAP[d.status] ?? d.status} /><span className="text-[11.5px] text-fg-subtle">{timeAgo(d.updated_at)}</span></div>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        </div>
        {!current ? <Card><EmptyState icon={BookOpenText} title="Start with a brief">Enter a target query to generate an outline and draft.</EmptyState></Card> : (
          <Card>
            <CardHeader
              title={current.title}
              description={<>Target query: “{current.target_query}” · {current.ai_generated ? <Badge tone="accent">AI draft</Badge> : <Badge tone="warning">Template brief (no AI model)</Badge>}</>}
              action={<StatusBadge status={STATUS_MAP[current.status] ?? current.status} />}
            />
            <CardBody className="space-y-5">
              <div className="grid gap-4 lg:grid-cols-2">
                <div>
                  <p className="mb-1.5 text-[11.5px] uppercase tracking-wide text-fg-subtle">Draft (markdown)</p>
                  <Textarea value={body} onChange={(e) => setBody(e.target.value)} readOnly={!editable} aria-label="Draft body" className="min-h-[420px] font-mono text-[12.5px]" />
                </div>
                <div>
                  <p className="mb-1.5 text-[11.5px] uppercase tracking-wide text-fg-subtle">Brief</p>
                  <div className="space-y-4 rounded-xl border border-border bg-surface-2 p-4 text-[13px]">
                    {current.brief.search_intent && <div><p className="font-medium">Search intent</p><p className="text-fg-muted">{current.brief.search_intent}</p></div>}
                    {[["Outline", current.brief.outline], ["Key points", current.brief.key_points], ["Internal links", current.brief.internal_link_suggestions], ["Sources needed", current.brief.sources_needed]].map(([label, items]) =>
                      (items as string[] | undefined)?.length ? (
                        <div key={label as string}><p className="font-medium">{label as string}</p><ul className="mt-1 list-disc space-y-0.5 pl-5 text-fg-muted">{(items as string[]).map((x) => <li key={x}>{x}</li>)}</ul></div>
                      ) : null,
                    )}
                    {current.brief.caveats?.length ? <p className="text-[12px] text-fg-subtle">{current.brief.caveats.join(" ")}</p> : null}
                  </div>
                </div>
              </div>
              {current.review_notes && <Alert tone="info" title="Reviewer notes">{current.review_notes}</Alert>}
              <Alert tone="warning">{current.publishing}</Alert>
              {(editable || (current.status === "in_review" && canApprove)) && (
                <Field label="Note (optional)" htmlFor="notes2"><Input id="notes2" value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
              )}
              <div className="flex flex-wrap gap-2">
                {editable && <><Button variant="secondary" onClick={() => act.mutate("save")}><Save /> Save</Button><Button onClick={() => act.mutate("submit")}><Send /> Submit for review</Button></>}
                {current.status === "in_review" && canApprove && <><Button variant="danger-outline" onClick={() => act.mutate("reject")}><X /> Request changes</Button><Button variant="success" onClick={() => act.mutate("approve")}><Check /> Editorial approval</Button></>}
              </div>
            </CardBody>
          </Card>
        )}
      </div>
    </div>
  );
}
