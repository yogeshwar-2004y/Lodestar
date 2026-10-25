"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileBarChart } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, EmptyState, Field, NativeSelect, Table, Td, Th } from "@/components/ui/core";
import { ApiError, http } from "@/lib/api";
import { useCan, useSites } from "@/lib/hooks";
import { fmtDate } from "@/lib/utils";

type Report = { id: string; title: string; site: string; status: string; period_start: string | null; period_end: string | null; created_at: string; download_url: string | null };

export default function Reports() {
  const qc = useQueryClient();
  const sites = useSites();
  const canCreate = useCan("report:create");
  const reports = useQuery({ queryKey: ["reports"], queryFn: () => http<Report[]>("/reports") });
  const create = useMutation({
    mutationFn: (b: { site_id: string; period_days: number }) => http("/reports", { json: b }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["reports"] }); toast.success("Report generated"); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Reports" description="Branded PDF reports per client workspace. Only real data is included; demo data is labelled; no ranking claims." />
      {canCreate && (
        <Card className="mb-5">
          <CardHeader title="Generate a report" />
          <CardBody>
            <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); create.mutate({ site_id: String(f.get("site")), period_days: Number(f.get("days")) }); }}>
              <Field label="Site" htmlFor="site"><NativeSelect id="site" name="site" required>{sites.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</NativeSelect></Field>
              <Field label="Period" htmlFor="days"><NativeSelect id="days" name="days" defaultValue="28"><option value="7">7 days</option><option value="28">28 days</option><option value="90">90 days</option></NativeSelect></Field>
              <Button type="submit" loading={create.isPending} disabled={!sites.data?.length}><FileBarChart /> Generate PDF</Button>
            </form>
          </CardBody>
        </Card>
      )}
      <Card>
        {reports.data?.length === 0 ? <EmptyState icon={FileBarChart} title="No reports yet" /> : (
          <Table>
            <thead><tr><Th>Report</Th><Th>Site</Th><Th className="hidden md:table-cell">Period</Th><Th>Status</Th><Th /></tr></thead>
            <tbody>
              {reports.data?.map((r) => (
                <tr key={r.id}>
                  <Td className="font-medium">{r.title}</Td>
                  <Td className="text-fg-muted">{r.site}</Td>
                  <Td className="hidden text-fg-muted md:table-cell">{fmtDate(r.period_start)} – {fmtDate(r.period_end)}</Td>
                  <Td><Badge tone={r.status === "ready" ? "success" : "info"}>{r.status}</Badge></Td>
                  <Td className="text-right">{r.download_url && <Button asChild size="sm" variant="secondary"><a href={r.download_url} target="_blank" rel="noreferrer"><Download /> PDF</a></Button>}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
