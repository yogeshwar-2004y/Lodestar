"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ExternalLink, FileSearch, Search } from "lucide-react";
import { useParams } from "next/navigation";
import * as React from "react";

import { SerpPreview, SeverityBadge } from "@/components/app/domain";
import { ErrorState, PageHeader } from "@/components/app/page-header";
import { FixButton } from "@/components/app/fix-button";
import { Button } from "@/components/ui/button";
import { Badge, Card, Dialog, DialogContent, EmptyState, Input, NativeSelect, Skeleton, Table, Td, Th } from "@/components/ui/core";
import { http } from "@/lib/api";
import { fmtDate, pathOf } from "@/lib/utils";

type PageRow = { id: string; url: string; path: string; status_code: number | null; title: string | null; meta_description: string | null; h1: string | null; indexable: boolean | null; in_sitemap: boolean; depth: number | null; word_count: number | null; inlinks: number; response_ms: number | null; redirect_target: string | null; canonical: string | null; robots_meta: string | null };
type PageDetail = {
  page: PageRow;
  snapshot: { jsonld?: { valid_json: boolean; types?: string[] }[]; headings?: { level: number; text: string }[] } | null;
  snapshots: { id: string; status_code: number; content_hash: string | null; changed: boolean; fetched_at: string | null; response_ms: number | null; redirect_chain: { url: string; status: number }[] }[];
  findings: { finding_id: string; rule_key: string; title: string; severity: string; kind: string; fix_action: string | null; status: string; evidence: Record<string, unknown> }[];
};

export default function Explorer() {
  const { siteId } = useParams<{ siteId: string }>();
  const [q, setQ] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [indexable, setIndexable] = React.useState("");
  const [selected, setSelected] = React.useState<string | null>(null);
  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);
  const params = new URLSearchParams({ limit: "50", ...(debounced && { q: debounced }), ...(status && { status }), ...(indexable && { indexable }) });
  const pages = useInfiniteQuery({
    queryKey: ["pages", siteId, params.toString()],
    queryFn: ({ pageParam }) => http<{ items: PageRow[]; next_cursor: string | null }>(`/sites/${siteId}/pages?${params}${pageParam ? `&cursor=${pageParam}` : ""}`),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const rows = pages.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Site explorer" description="Every crawled URL with its page-level SEO diagnostics and crawl snapshots." />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
          <div className="relative min-w-[220px] flex-1">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
            <Input aria-label="Search URLs or titles" placeholder="Search URL or title…" value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" />
          </div>
          <NativeSelect aria-label="Status code" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {["200", "301", "302", "404", "410", "500"].map((s) => <option key={s}>{s}</option>)}
          </NativeSelect>
          <NativeSelect aria-label="Indexability" value={indexable} onChange={(e) => setIndexable(e.target.value)}>
            <option value="">Any indexability</option>
            <option value="true">Indexable</option>
            <option value="false">Not indexable</option>
          </NativeSelect>
        </div>
        {pages.error && <div className="p-4"><ErrorState error={pages.error} /></div>}
        <Table>
          <thead>
            <tr>
              <Th>URL</Th>
              <Th>Status</Th>
              <Th className="hidden md:table-cell">Title</Th>
              <Th className="hidden lg:table-cell">Description</Th>
              <Th className="hidden md:table-cell">Index</Th>
              <Th className="hidden xl:table-cell text-right">Words</Th>
              <Th className="hidden xl:table-cell text-right">Inlinks</Th>
            </tr>
          </thead>
          <tbody>
            {pages.isLoading && [...Array(6)].map((_, i) => (
              <tr key={i}><Td colSpan={7}><Skeleton className="h-5" /></Td></tr>
            ))}
            {rows.map((p) => (
              <tr key={p.id} onClick={() => setSelected(p.id)} className="cursor-pointer hover:bg-bg-subtle/60" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setSelected(p.id)}>
                <Td className="max-w-[280px]">
                  <span className="block truncate font-mono text-[12.5px]">{pathOf(p.url)}</span>
                  {p.redirect_target && <span className="block truncate text-[11.5px] text-fg-subtle">→ {pathOf(p.redirect_target)}</span>}
                </Td>
                <Td><StatusCode code={p.status_code} /></Td>
                <Td className="hidden max-w-[240px] truncate md:table-cell">{p.title ?? <Missing />}</Td>
                <Td className="hidden max-w-[300px] truncate text-fg-muted lg:table-cell">{p.meta_description || <Missing />}</Td>
                <Td className="hidden md:table-cell">{p.indexable === null ? "—" : p.indexable ? <Badge tone="success">Yes</Badge> : <Badge>No</Badge>}</Td>
                <Td className="hidden text-right tabular xl:table-cell">{p.word_count ?? "—"}</Td>
                <Td className="hidden text-right tabular xl:table-cell">{p.inlinks}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        {!pages.isLoading && rows.length === 0 && <EmptyState icon={FileSearch} title="No pages match">Try a different filter, or run a crawl.</EmptyState>}
        {pages.hasNextPage && (
          <div className="flex justify-center p-3">
            <Button variant="secondary" onClick={() => pages.fetchNextPage()} loading={pages.isFetchingNextPage}>Load more</Button>
          </div>
        )}
      </Card>
      <PageDrawer siteId={siteId} pageId={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

function Missing() {
  return <span className="text-[12px] italic text-danger">missing</span>;
}

function StatusCode({ code }: { code: number | null }) {
  if (!code) return <Badge tone="neutral">blocked</Badge>;
  const tone = code >= 500 ? "danger" : code >= 400 ? "danger" : code >= 300 ? "warning" : "success";
  return <Badge tone={tone}>{code}</Badge>;
}

function PageDrawer({ siteId, pageId, onClose }: { siteId: string; pageId: string | null; onClose: () => void }) {
  const { data, isLoading } = useQuery({ queryKey: ["page", pageId], queryFn: () => http<PageDetail>(`/pages/${pageId}`), enabled: !!pageId });
  const s = data?.snapshot;
  return (
    <Dialog open={!!pageId} onOpenChange={(o) => !o && onClose()}>
      <DialogContent side="right" title="URL inspection" description={data ? pathOf(data.page.url) : undefined}>
        {isLoading || !data ? (
          <div className="space-y-3"><Skeleton className="h-24" /><Skeleton className="h-40" /></div>
        ) : (
          <div className="space-y-6">
            <div className="flex flex-wrap gap-2">
              <StatusCode code={data.page.status_code} />
              {data.page.indexable ? <Badge tone="success">Indexable</Badge> : <Badge>Not indexable</Badge>}
              {data.page.in_sitemap && <Badge tone="info">In sitemap</Badge>}
              <a href={data.page.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-[12.5px] text-accent hover:underline">
                Open <ExternalLink className="size-3" />
              </a>
            </div>
            <SerpPreview url={data.page.url} title={data.page.title} description={data.page.meta_description} />
            <section>
              <h3 className="mb-2 text-[13px] font-semibold">Diagnostics</h3>
              <dl className="grid grid-cols-[140px_1fr] gap-x-3 gap-y-2 text-[13px]">
                <dt className="text-fg-subtle">Title</dt><dd>{data.page.title ?? <Missing />} {data.page.title && <span className="text-fg-subtle">({data.page.title.length})</span>}</dd>
                <dt className="text-fg-subtle">Meta description</dt><dd>{data.page.meta_description || <Missing />}</dd>
                <dt className="text-fg-subtle">H1</dt><dd>{data.page.h1 ?? <Missing />}</dd>
                <dt className="text-fg-subtle">Canonical</dt><dd className="break-all font-mono text-[12px]">{data.page.canonical ?? "—"}</dd>
                <dt className="text-fg-subtle">Robots</dt><dd>{data.page.robots_meta ?? "—"}</dd>
                <dt className="text-fg-subtle">Words · inlinks</dt><dd className="tabular">{data.page.word_count ?? "—"} · {data.page.inlinks}</dd>
                <dt className="text-fg-subtle">Response</dt><dd className="tabular">{data.page.response_ms ?? "—"} ms (crawler observation)</dd>
                <dt className="text-fg-subtle">Structured data</dt>
                <dd>{(s?.jsonld ?? []).length ? (s?.jsonld ?? []).map((b, i) => <Badge key={i} tone={b.valid_json ? "teal" : "danger"} className="mr-1">{b.valid_json ? (b.types ?? []).join(", ") || "untyped" : "invalid JSON"}</Badge>) : "none"}</dd>
              </dl>
            </section>
            {!!s?.headings?.length && (
              <section>
                <h3 className="mb-2 text-[13px] font-semibold">Heading outline</h3>
                <ul className="space-y-1 text-[12.5px]">
                  {s.headings.slice(0, 20).map((h, i) => (
                    <li key={i} style={{ paddingLeft: (h.level - 1) * 14 }} className="truncate"><span className="mr-2 font-mono text-fg-subtle">H{h.level}</span>{h.text}</li>
                  ))}
                </ul>
              </section>
            )}
            <section>
              <h3 className="mb-2 text-[13px] font-semibold">Issues on this page</h3>
              {data.findings.length === 0 && <p className="text-[13px] text-fg-muted">No open issues.</p>}
              <ul className="space-y-2">
                {data.findings.map((f) => (
                  <li key={f.finding_id} className="flex items-center justify-between gap-2 rounded-lg border border-border px-3 py-2">
                    <span className="text-[13px]">{f.title}</span>
                    <span className="flex items-center gap-1.5">
                      <SeverityBadge severity={f.severity} />
                      {f.fix_action && f.status === "open" && <FixButton siteId={siteId} url={data.page.url} action={f.fix_action} findingId={f.finding_id} size="sm" />}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <h3 className="mb-2 text-[13px] font-semibold">Crawl snapshots</h3>
              <ul className="space-y-1.5 text-[12.5px]">
                {data.snapshots.map((sn) => (
                  <li key={sn.id} className="flex items-center justify-between rounded-md bg-bg-subtle px-3 py-1.5">
                    <span>{fmtDate(sn.fetched_at, true)}</span>
                    <span className="flex items-center gap-2 font-mono text-fg-muted">
                      {sn.status_code} · {sn.content_hash?.slice(0, 8) ?? "—"} {sn.changed && <Badge tone="info">changed</Badge>}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
