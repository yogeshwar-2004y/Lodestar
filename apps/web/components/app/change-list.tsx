"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Inbox } from "lucide-react";
import Link from "next/link";

import { RiskMeter, StatusBadge } from "@/components/app/domain";
import { Button } from "@/components/ui/button";
import { Badge, EmptyState, Skeleton, Table, Td, Th } from "@/components/ui/core";
import { http } from "@/lib/api";
import { useSites } from "@/lib/hooks";
import { timeAgo } from "@/lib/utils";

type Row = { id: string; site_id: string; title: string; status: string; risk_score: number | null; risk_level: string | null; source: string; is_fixture: boolean; action_type: string; updated_at: string };

export function ChangeList({ siteId, status, emptyTitle, emptyBody }: { siteId?: string; status?: string; emptyTitle: string; emptyBody?: string }) {
  const sites = useSites();
  const qs = new URLSearchParams({ limit: "25", ...(siteId && { site_id: siteId }), ...(status && { status }) });
  const q = useInfiniteQuery({
    queryKey: ["changes", siteId ?? "all", status ?? "all"],
    queryFn: ({ pageParam }) => http<{ items: Row[]; next_cursor: string | null }>(`/change-sets?${qs}${pageParam ? `&cursor=${pageParam}` : ""}`),
    initialPageParam: "",
    getNextPageParam: (l) => l.next_cursor ?? undefined,
    refetchInterval: 10_000,
  });
  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];
  const siteName = (id: string) => sites.data?.find((s) => s.id === id)?.name ?? "";
  if (q.isLoading) return <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>;
  if (!rows.length) return <EmptyState icon={Inbox} title={emptyTitle}>{emptyBody}</EmptyState>;
  return (
    <>
      <Table>
        <thead>
          <tr>
            <Th>Change</Th>
            {!siteId && <Th className="hidden md:table-cell">Site</Th>}
            <Th>Status</Th>
            <Th className="hidden lg:table-cell">Risk</Th>
            <Th className="hidden md:table-cell">Source</Th>
            <Th className="text-right">Updated</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="hover:bg-bg-subtle/60">
              <Td className="max-w-[360px]">
                <Link href={`/app/fixes/${r.id}`} className="block truncate font-medium hover:text-accent">{r.title}</Link>
                {r.is_fixture && <Badge tone="warning" className="mt-1">Fixture</Badge>}
              </Td>
              {!siteId && <Td className="hidden text-fg-muted md:table-cell">{siteName(r.site_id)}</Td>}
              <Td><StatusBadge status={r.status} /></Td>
              <Td className="hidden lg:table-cell"><RiskMeter score={r.risk_score} level={r.risk_level} /></Td>
              <Td className="hidden md:table-cell"><Badge tone={r.source === "ai" ? "accent" : "neutral"}>{r.source}</Badge></Td>
              <Td className="text-right text-[12px] text-fg-subtle">{timeAgo(r.updated_at)}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {q.hasNextPage && <div className="flex justify-center p-3"><Button variant="secondary" onClick={() => q.fetchNextPage()} loading={q.isFetchingNextPage}>Load more</Button></div>}
    </>
  );
}
