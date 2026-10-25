"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Plus, UserPlus } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, CardBody, CardHeader, Dialog, DialogContent, EmptyState, Field, Input, NativeSelect } from "@/components/ui/core";
import { ApiError, http } from "@/lib/api";
import { useCan, useSession, useSites } from "@/lib/hooks";

type Workspace = { id: string; name: string; slug: string; is_default: boolean; branding: { primary_color?: string; agency_name?: string } };
type Member = { user_id: string; email: string; name: string; role: string; workspaces: string[] };

export default function Workspaces() {
  const qc = useQueryClient();
  const welcome = useSearchParams().get("welcome");
  const session = useSession();
  const canManage = useCan("workspace:manage");
  const canMembers = useCan("members:manage");
  const ws = useQuery({ queryKey: ["workspaces"], queryFn: () => http<Workspace[]>("/workspaces") });
  const members = useQuery({ queryKey: ["members"], queryFn: () => http<Member[]>("/organizations/current/members") });
  const sites = useSites();
  const [open, setOpen] = React.useState<null | "ws" | "member">(null);
  const onErr = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Failed");
  const createWs = useMutation({ mutationFn: (b: Record<string, unknown>) => http("/workspaces", { json: b }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["workspaces"] }); setOpen(null); toast.success("Workspace created"); }, onError: onErr });
  const addMember = useMutation({ mutationFn: (b: Record<string, unknown>) => http("/organizations/current/members", { json: b }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["members"] }); setOpen(null); toast.success("Member added"); }, onError: onErr });
  const isAgency = session.data?.organization?.kind === "agency";
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title={isAgency ? "Client workspaces" : "Workspaces"}
        description="Workspaces separate sites, people and branded reports. Client users only ever see the workspaces they're assigned to."
        actions={<>{canMembers && <Button variant="secondary" onClick={() => setOpen("member")}><UserPlus /> Add person</Button>}{canManage && <Button onClick={() => setOpen("ws")}><Plus /> New workspace</Button>}</>}
      />
      {welcome && <Alert tone="info" className="mb-5" title="Welcome!">Create a workspace for each client, then add their sites and invite client users.</Alert>}
      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {ws.data?.map((w) => {
          const wsSites = sites.data?.filter((s) => s.workspace_id === w.id) ?? [];
          const people = members.data?.filter((m) => m.workspaces.includes(w.id)) ?? [];
          return (
            <Card key={w.id} className="overflow-hidden">
              <div className="h-1.5" style={{ background: w.branding.primary_color ?? "var(--accent)" }} />
              <CardHeader title={w.name} description={w.is_default ? "Default workspace" : w.branding.agency_name} action={<Building2 className="size-4 text-fg-subtle" />} />
              <CardBody className="space-y-3 text-[13px]">
                <div>
                  <p className="mb-1 text-[11.5px] uppercase tracking-wide text-fg-subtle">Sites</p>
                  {wsSites.length === 0 ? <p className="text-fg-muted">None yet</p> : wsSites.map((s) => <Link key={s.id} href={`/app/sites/${s.id}`} className="block truncate hover:text-accent">{s.name} <span className="text-fg-subtle">· {s.health_score ?? "—"}</span></Link>)}
                </div>
                <div>
                  <p className="mb-1 text-[11.5px] uppercase tracking-wide text-fg-subtle">People</p>
                  <div className="flex flex-wrap gap-1.5">{people.map((p) => <Badge key={p.user_id} tone={p.role === "client" ? "teal" : "neutral"}>{p.name} · {p.role}</Badge>)}</div>
                </div>
              </CardBody>
            </Card>
          );
        })}
      </div>
      {ws.data?.length === 0 && <Card><EmptyState icon={Building2} title="No workspaces" /></Card>}
      {members.data && (
        <Card className="mt-6">
          <CardHeader title="People & roles" description="owner > admin > editor > analyst > viewer. Client users see only assigned workspaces." />
          <CardBody className="divide-y divide-border">
            {members.data.map((m) => (
              <div key={m.user_id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-[13px]">
                <span><b>{m.name}</b> <span className="text-fg-muted">{m.email}</span></span>
                <span className="flex items-center gap-2"><Badge tone="accent">{m.role}</Badge><span className="text-fg-subtle">{m.workspaces.length} workspace(s)</span></span>
              </div>
            ))}
          </CardBody>
        </Card>
      )}
      <Dialog open={open === "ws"} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent title="New workspace" description="Branding is used on PDF reports for this client.">
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); createWs.mutate({ name: f.get("name"), branding: { agency_name: f.get("agency") || undefined, primary_color: f.get("color") } }); }}>
            <Field label="Client / workspace name" htmlFor="wsn"><Input id="wsn" name="name" required /></Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Report header name" htmlFor="ag"><Input id="ag" name="agency" placeholder={session.data?.organization?.name} /></Field>
              <Field label="Brand color" htmlFor="col"><Input id="col" name="color" type="color" defaultValue="#4f46e5" className="h-9 p-1" /></Field>
            </div>
            <Button type="submit" loading={createWs.isPending}>Create</Button>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog open={open === "member"} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent title="Add a person" description="New users get the initial password you set and should change it after signing in.">
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); addMember.mutate({ email: f.get("email"), name: f.get("name"), role: f.get("role"), password: f.get("password") || undefined, workspace_ids: f.getAll("ws") }); }}>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Name" htmlFor="mn"><Input id="mn" name="name" required /></Field>
              <Field label="Email" htmlFor="me"><Input id="me" name="email" type="email" required /></Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Role" htmlFor="mr">
                <NativeSelect id="mr" name="role" defaultValue="editor" className="w-full">{["admin", "editor", "analyst", "viewer", "client"].map((r) => <option key={r}>{r}</option>)}</NativeSelect>
              </Field>
              <Field label="Initial password" htmlFor="mp" hint="Only for new accounts (10+ chars)"><Input id="mp" name="password" type="password" minLength={10} /></Field>
            </div>
            <fieldset>
              <legend className="mb-1.5 text-[13px] font-medium">Workspaces</legend>
              <div className="flex flex-wrap gap-3">{ws.data?.map((w) => <label key={w.id} className="flex items-center gap-1.5 text-[13px]"><input type="checkbox" name="ws" value={w.id} /> {w.name}</label>)}</div>
              <p className="mt-1 text-[11.5px] text-fg-subtle">Client users require at least one workspace. Others default to the default workspace.</p>
            </fieldset>
            <Button type="submit" loading={addMember.isPending}>Add</Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
