"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";

import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, Table, Td, Th } from "@/components/ui/core";
import { http } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

type Ev = { id: string; created_at: string; actor_type: string; actor: string | null; action: string; target_type: string | null; target_id: string | null; data: Record<string, unknown>; hash: string };

export default function AuditLog() {
  const chain = useQuery({ queryKey: ["audit-verify"], queryFn: () => http<{ valid: boolean; checked: number; broken_at?: string }>("/audit-events/verify") });
  const q = useInfiniteQuery({
    queryKey: ["audit-log"],
    queryFn: ({ pageParam }) => http<{ items: Ev[]; next_cursor: string | null }>(`/audit-events?limit=50${pageParam ? `&cursor=${pageParam}` : ""}`),
    initialPageParam: "",
    getNextPageParam: (l) => l.next_cursor ?? undefined,
  });
  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Audit log"
        description="Append-only and hash-chained. Secrets are never recorded."
        eyebrow={chain.data && (chain.data.valid ? <Badge tone="success"><ShieldCheck className="size-3" /> Chain intact · {chain.data.checked} events verified</Badge> : <Badge tone="danger">Chain broken at {chain.data.broken_at}</Badge>)}
      />
      <Card>
        <Table>
          <thead><tr><Th>When</Th><Th>Actor</Th><Th>Action</Th><Th className="hidden md:table-cell">Target</Th><Th className="hidden lg:table-cell">Details</Th><Th className="hidden xl:table-cell">Hash</Th></tr></thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id}>
                <Td className="whitespace-nowrap text-fg-muted">{fmtDate(e.created_at, true)}</Td>
                <Td><Badge tone={e.actor_type === "user" ? "neutral" : e.actor_type === "agent" ? "accent" : "teal"}>{e.actor_type}</Badge> <span className="text-[12px]">{e.actor}</span></Td>
                <Td className="font-mono text-[12px]">{e.action}</Td>
                <Td className="hidden font-mono text-[11.5px] text-fg-subtle md:table-cell">{e.target_type}:{e.target_id?.slice(0, 8)}</Td>
                <Td className="hidden max-w-[280px] truncate font-mono text-[11px] text-fg-muted lg:table-cell">{JSON.stringify(e.data)}</Td>
                <Td className="hidden font-mono text-[11px] text-fg-subtle xl:table-cell">{e.hash.slice(0, 10)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        {q.hasNextPage && <div className="flex justify-center p-3"><Button variant="secondary" onClick={() => q.fetchNextPage()} loading={q.isFetchingNextPage}>Load more</Button></div>}
      </Card>
    </div>
  );
}
