"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Command } from "cmdk";
import {
  Activity,
  Bell,
  BookOpenText,
  Bot,
  Building2,
  ChevronsLeft,
  ChevronsUpDown,
  CreditCard,
  FileBarChart,
  Gauge,
  Globe,
  Inbox,
  LayoutDashboard,
  LineChart,
  LogOut,
  Monitor,
  Moon,
  Plus,
  ScrollText,
  Search,
  Settings,
  ShieldAlert,
  Sparkles,
  Sun,
  Target,
  Wand2,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";

import { Logo } from "@/components/marketing/chrome";
import { useTheme } from "@/components/providers";
import { Badge, Kbd } from "@/components/ui/core";
import { ApiError, http } from "@/lib/api";
import { type Site, useMeta, useSession, useSites } from "@/lib/hooks";
import { cn, timeAgo } from "@/lib/utils";

type NavItem = { href: string; label: string; icon: React.ComponentType<{ className?: string }>; perm?: string };

function siteNav(siteId: string): NavItem[] {
  const b = `/app/sites/${siteId}`;
  return [
    { href: b, label: "Overview", icon: LayoutDashboard },
    { href: `${b}/explorer`, label: "Site explorer", icon: Globe },
    { href: `${b}/audit`, label: "Audit center", icon: Gauge },
    { href: `${b}/copilot`, label: "AI Copilot", icon: Sparkles, perm: "copilot:use" },
    { href: `${b}/strategy`, label: "Strategy", icon: Target },
    { href: `${b}/content`, label: "Content Studio", icon: BookOpenText },
    { href: `${b}/fixes`, label: "Auto-Fix center", icon: Wand2 },
    { href: `${b}/automations`, label: "Automations", icon: Workflow, perm: "automation:read" },
    { href: `${b}/analytics`, label: "Analytics", icon: LineChart },
    { href: `${b}/settings`, label: "Site settings", icon: Settings },
  ];
}

const ORG_NAV: NavItem[] = [
  { href: "/app/approvals", label: "Approval inbox", icon: Inbox },
  { href: "/app/workspaces", label: "Workspaces", icon: Building2 },
  { href: "/app/reports", label: "Reports", icon: FileBarChart },
  { href: "/app/audit-log", label: "Audit log", icon: ScrollText, perm: "audit:read" },
  { href: "/app/billing", label: "Billing & usage", icon: CreditCard, perm: "usage:read" },
  { href: "/app/settings", label: "Settings", icon: Settings },
];

export function useCurrentSiteId(sites?: Site[]) {
  const pathname = usePathname();
  const m = pathname.match(/\/app\/sites\/([0-9a-f-]{36})/);
  const [stored, setStored] = React.useState<string | null>(null);
  React.useEffect(() => {
    try {
      setStored(localStorage.getItem("ls-site"));
    } catch {}
  }, []);
  const id = m?.[1] ?? (sites?.some((s) => s.id === stored) ? stored : sites?.[0]?.id) ?? null;
  React.useEffect(() => {
    if (m?.[1]) {
      try {
        localStorage.setItem("ls-site", m[1]);
      } catch {}
    }
  }, [m]);
  return id;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const session = useSession();
  const sites = useSites();
  const meta = useMeta();
  const [collapsed, setCollapsed] = React.useState(false);
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [paletteOpen, setPaletteOpen] = React.useState(false);
  const siteId = useCurrentSiteId(sites.data);

  React.useEffect(() => {
    if (session.error instanceof ApiError && session.error.status === 401) router.replace(`/signin?next=${encodeURIComponent(pathname)}`);
    if (session.data && !session.data.organization) router.replace("/onboarding");
  }, [session.error, session.data, router, pathname]);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  React.useEffect(() => { setMobileOpen(false); }, [pathname]);

  if (session.isLoading || !session.data?.organization) {
    return (
      <div className="grid min-h-dvh place-items-center" aria-busy>
        <Logo className="animate-pulse" />
      </div>
    );
  }
  const perms = new Set(session.data.permissions);
  const can = (p?: string) => !p || perms.has(p);
  const org = session.data.organization;
  const site = sites.data?.find((s) => s.id === siteId);

  const nav = (
    <nav className="flex h-full flex-col gap-6 overflow-y-auto px-3 py-4" aria-label="App">
      <div className="flex items-center justify-between px-2">
        <Link href="/app" aria-label="Home">
          {collapsed ? <Logo className="[&>span:last-child]:hidden" /> : <Logo />}
        </Link>
        <button onClick={() => setCollapsed((v) => !v)} className="hidden rounded-md p-1 text-fg-subtle hover:bg-bg-subtle hover:text-fg lg:block" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
          <ChevronsLeft className={cn("size-4 transition-transform", collapsed && "rotate-180")} />
        </button>
      </div>
      {siteId && (
        <NavGroup label={collapsed ? undefined : "Site"} items={siteNav(siteId).filter((i) => can(i.perm))} pathname={pathname} collapsed={collapsed} exactFirst />
      )}
      <NavGroup label={collapsed ? undefined : "Organization"} items={ORG_NAV.filter((i) => can(i.perm))} pathname={pathname} collapsed={collapsed} />
      {!collapsed && meta.data && (
        <div className="mt-auto rounded-xl border border-border bg-bg-subtle/60 p-3 text-[11.5px] text-fg-muted">
          <div className="flex items-center gap-1.5 font-medium text-fg">
            <Bot className="size-3.5" /> AI: {meta.data.ai_mode === "llm" ? meta.data.ai_model : "deterministic fallback"}
          </div>
          {meta.data.ai_mode !== "llm" && <p className="mt-1">No model configured — drafts and answers use labelled templates.</p>}
        </div>
      )}
    </nav>
  );

  return (
    <div className="flex min-h-dvh">
      <aside className={cn("sticky top-0 hidden h-dvh shrink-0 border-r border-border bg-surface/70 backdrop-blur transition-[width] duration-200 lg:block", collapsed ? "w-[68px]" : "w-[248px]")}>{nav}</aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <button className="absolute inset-0 bg-black/30" onClick={() => setMobileOpen(false)} aria-label="Close navigation" />
          <aside className="relative h-full w-[272px] border-r border-border bg-surface">{nav}</aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        {org.kill_switch && (
          <div className="flex items-center justify-center gap-2 bg-danger px-4 py-2 text-[13px] font-medium text-white" role="alert">
            <ShieldAlert className="size-4" /> Emergency kill switch is engaged — no changes will be executed.
            <Link href="/app/settings" className="underline">Manage</Link>
          </div>
        )}
        {(site?.is_demo || org.is_demo) && (
          <div className="bg-warning-soft px-4 py-1.5 text-center text-[12.5px] text-warning">
            Demo environment — data and connectors here are labelled fixtures, not a real customer site.
          </div>
        )}
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border bg-bg/85 px-4 backdrop-blur-md sm:px-6">
          <button className="rounded-md p-1.5 hover:bg-bg-subtle lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
            <ChevronsUpDown className="size-4 rotate-90" />
          </button>
          <SiteSelector sites={sites.data ?? []} current={site} />
          <Breadcrumbs pathname={pathname} site={site} />
          <div className="ml-auto flex items-center gap-1.5">
            <button
              onClick={() => setPaletteOpen(true)}
              className="hidden h-9 items-center gap-2 rounded-[10px] border border-border bg-surface px-3 text-[13px] text-fg-subtle hover:border-border-strong sm:flex"
              aria-label="Open command palette"
            >
              <Search className="size-4" /> Search or jump to… <Kbd>⌘K</Kbd>
            </button>
            <Notifications />
            <ProfileMenu name={session.data.user.name} email={session.data.user.email} org={org.name} role={session.data.role ?? ""} memberships={session.data.memberships} />
          </div>
        </header>
        <main id="main" className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">
          {children}
        </main>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} sites={sites.data ?? []} siteId={siteId} />
    </div>
  );
}

function NavGroup({ label, items, pathname, collapsed, exactFirst }: { label?: string; items: NavItem[]; pathname: string; collapsed: boolean; exactFirst?: boolean }) {
  return (
    <div>
      {label && <p className="mb-1.5 px-2 text-[10.5px] font-semibold uppercase tracking-wider text-fg-subtle">{label}</p>}
      <ul className="space-y-0.5">
        {items.map((it, i) => {
          const active = exactFirst && i === 0 ? pathname === it.href : pathname === it.href || pathname.startsWith(it.href + "/");
          return (
            <li key={it.href}>
              <Link
                href={it.href}
                title={collapsed ? it.label : undefined}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-[13.5px] transition-colors",
                  active ? "bg-accent-soft font-medium text-accent" : "text-fg-muted hover:bg-bg-subtle hover:text-fg",
                  collapsed && "justify-center px-0",
                )}
              >
                <it.icon className="size-4 shrink-0" aria-hidden />
                {!collapsed && it.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function SiteSelector({ sites, current }: { sites: Site[]; current?: Site }) {
  const router = useRouter();
  const pathname = usePathname();
  return (
    <Dropdown.Root>
      <Dropdown.Trigger className="flex h-9 max-w-[220px] items-center gap-2 rounded-[10px] border border-border bg-surface px-3 text-[13px] hover:border-border-strong" aria-label="Select site">
        <Globe className="size-4 text-fg-subtle" />
        <span className="truncate font-medium">{current?.name ?? "Select a site"}</span>
        <ChevronsUpDown className="size-3.5 text-fg-subtle" />
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content align="start" sideOffset={6} className="z-50 w-72 rounded-xl border border-border bg-surface p-1.5 shadow-xl">
          {sites.map((s) => (
            <Dropdown.Item
              key={s.id}
              onSelect={() => {
                const rest = pathname.match(/\/app\/sites\/[0-9a-f-]{36}(\/.*)?$/)?.[1] ?? "";
                router.push(`/app/sites/${s.id}${rest}`);
              }}
              className="flex cursor-pointer items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-[13px] outline-none data-[highlighted]:bg-bg-subtle"
            >
              <span className="min-w-0">
                <span className="block truncate font-medium">{s.name}</span>
                <span className="block truncate text-[11.5px] text-fg-subtle">{s.domain}</span>
              </span>
              <span className="tabular text-[12px] text-fg-muted">{s.health_score ?? "—"}</span>
            </Dropdown.Item>
          ))}
          <Dropdown.Separator className="my-1 h-px bg-border" />
          <Dropdown.Item onSelect={() => router.push("/app/sites/new")} className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] text-accent outline-none data-[highlighted]:bg-bg-subtle">
            <Plus className="size-4" /> Add website
          </Dropdown.Item>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

const LABELS: Record<string, string> = {
  explorer: "Site explorer", audit: "Audit center", copilot: "AI Copilot", strategy: "Strategy", content: "Content Studio", fixes: "Auto-Fix center",
  automations: "Automations", analytics: "Analytics", settings: "Settings", approvals: "Approval inbox", workspaces: "Workspaces", reports: "Reports",
  billing: "Billing & usage", "audit-log": "Audit log", new: "Add website",
};

function Breadcrumbs({ pathname, site }: { pathname: string; site?: Site }) {
  const parts = pathname.split("/").filter(Boolean).slice(1);
  const crumbs: string[] = [];
  for (const p of parts) {
    if (p === "sites") continue;
    if (/^[0-9a-f-]{36}$/.test(p)) {
      crumbs.push(site && pathname.includes(`/sites/${p}`) ? site.name : "Detail");
      continue;
    }
    crumbs.push(LABELS[p] ?? p);
  }
  if (!crumbs.length) return null;
  return (
    <nav aria-label="Breadcrumb" className="hidden min-w-0 items-center gap-1.5 text-[13px] text-fg-subtle md:flex">
      {crumbs.map((c, i) => (
        <React.Fragment key={i}>
          <span aria-hidden>/</span>
          <span className={cn("truncate", i === crumbs.length - 1 && "text-fg")}>{c}</span>
        </React.Fragment>
      ))}
    </nav>
  );
}

type Notification = { id: string; kind: string; severity: string; title: string; body: string | null; link: string | null; read: boolean; created_at: string };

function Notifications() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["notifications"], queryFn: () => http<{ unread: number; items: Notification[] }>("/notifications"), refetchInterval: 20_000 });
  const markRead = useMutation({ mutationFn: () => http("/notifications/read", { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });
  return (
    <Dropdown.Root onOpenChange={(o) => !o && data?.unread && markRead.mutate()}>
      <Dropdown.Trigger className="relative rounded-[10px] p-2 text-fg-muted hover:bg-bg-subtle hover:text-fg" aria-label={`Notifications${data?.unread ? `, ${data.unread} unread` : ""}`}>
        <Bell className="size-4" />
        {!!data?.unread && <span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-danger ring-2 ring-bg" />}
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content align="end" sideOffset={6} className="z-50 w-96 rounded-xl border border-border bg-surface p-1.5 shadow-xl">
          <p className="px-2.5 py-2 text-[12px] font-semibold uppercase tracking-wide text-fg-subtle">Notifications</p>
          {!data?.items.length && <p className="px-2.5 pb-4 text-[13px] text-fg-muted">You&apos;re all caught up.</p>}
          <div className="max-h-96 overflow-y-auto">
            {data?.items.map((n) => (
              <Dropdown.Item key={n.id} asChild className="outline-none data-[highlighted]:bg-bg-subtle">
                <Link href={n.link ?? "#"} className="flex gap-3 rounded-lg px-2.5 py-2">
                  <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", n.severity === "critical" ? "bg-danger" : n.severity === "warning" ? "bg-warning" : n.severity === "success" ? "bg-success" : "bg-info", n.read && "opacity-30")} />
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium">{n.title}</span>
                    {n.body && <span className="block truncate text-[12px] text-fg-muted">{n.body}</span>}
                    <span className="text-[11px] text-fg-subtle">{timeAgo(n.created_at)}</span>
                  </span>
                </Link>
              </Dropdown.Item>
            ))}
          </div>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

function ProfileMenu({ name, email, org, role, memberships }: { name: string; email: string; org: string; role: string; memberships: { organization: { id: string; name: string }; role: string }[] }) {
  const { theme, setTheme } = useTheme();
  const router = useRouter();
  const qc = useQueryClient();
  const item = "flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] outline-none data-[highlighted]:bg-bg-subtle";
  return (
    <Dropdown.Root>
      <Dropdown.Trigger className="grid size-9 place-items-center rounded-full bg-gradient-to-br from-accent to-teal text-[13px] font-semibold text-white" aria-label="Account menu">
        {name.slice(0, 1).toUpperCase()}
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content align="end" sideOffset={6} className="z-50 w-64 rounded-xl border border-border bg-surface p-1.5 shadow-xl">
          <div className="px-2.5 py-2">
            <p className="text-[13px] font-medium">{name}</p>
            <p className="truncate text-[12px] text-fg-muted">{email}</p>
            <p className="mt-1 text-[12px] text-fg-subtle">
              {org} · <Badge tone="accent">{role}</Badge>
            </p>
          </div>
          <Dropdown.Separator className="my-1 h-px bg-border" />
          {memberships.length > 1 &&
            memberships.map((m) => (
              <Dropdown.Item
                key={m.organization.id}
                className={item}
                onSelect={async () => {
                  await http(`/auth/switch-organization/${m.organization.id}`, { method: "POST" });
                  await qc.invalidateQueries();
                  router.push("/app");
                }}
              >
                <Building2 className="size-4" /> {m.organization.name}
              </Dropdown.Item>
            ))}
          <div className="flex gap-1 p-1.5" role="radiogroup" aria-label="Theme">
            {([["light", Sun], ["dark", Moon], ["system", Monitor]] as const).map(([t, Icon]) => (
              <button key={t} role="radio" aria-checked={theme === t} onClick={() => setTheme(t)} className={cn("flex flex-1 items-center justify-center gap-1 rounded-md py-1.5 text-[12px] capitalize", theme === t ? "bg-accent-soft text-accent" : "text-fg-muted hover:bg-bg-subtle")}>
                <Icon className="size-3.5" /> {t}
              </button>
            ))}
          </div>
          <Dropdown.Separator className="my-1 h-px bg-border" />
          <Dropdown.Item
            className={item}
            onSelect={async () => {
              await http("/auth/logout", { method: "POST" });
              qc.clear();
              router.push("/signin");
            }}
          >
            <LogOut className="size-4" /> Sign out
          </Dropdown.Item>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

function CommandPalette({ open, onOpenChange, sites, siteId }: { open: boolean; onOpenChange: (v: boolean) => void; sites: Site[]; siteId: string | null }) {
  const router = useRouter();
  const go = (href: string) => {
    onOpenChange(false);
    router.push(href);
  };
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-start justify-center bg-black/30 pt-[14vh] backdrop-blur-[2px]" onClick={() => onOpenChange(false)}>
      <Command
        label="Command palette"
        className="w-[min(640px,calc(100vw-32px))] overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && onOpenChange(false)}
      >
        <div className="flex items-center gap-2 border-b border-border px-4">
          <Search className="size-4 text-fg-subtle" />
          <Command.Input autoFocus placeholder="Jump to a page, site or action…" className="h-12 flex-1 bg-transparent text-[14px] outline-none placeholder:text-fg-subtle" />
          <Kbd>Esc</Kbd>
        </div>
        <Command.List className="max-h-[360px] overflow-y-auto p-2">
          <Command.Empty className="px-3 py-6 text-center text-[13px] text-fg-muted">No results.</Command.Empty>
          {siteId && (
            <Command.Group heading="This site" className="text-[11px] text-fg-subtle [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
              {siteNav(siteId).map((n) => (
                <PaletteItem key={n.href} onSelect={() => go(n.href)} icon={n.icon} label={n.label} />
              ))}
            </Command.Group>
          )}
          <Command.Group heading="Organization" className="text-[11px] text-fg-subtle [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
            {ORG_NAV.map((n) => (
              <PaletteItem key={n.href} onSelect={() => go(n.href)} icon={n.icon} label={n.label} />
            ))}
            <PaletteItem onSelect={() => go("/app/sites/new")} icon={Plus} label="Add website" />
          </Command.Group>
          <Command.Group heading="Sites" className="text-[11px] text-fg-subtle [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
            {sites.map((s) => (
              <PaletteItem key={s.id} onSelect={() => go(`/app/sites/${s.id}`)} icon={Activity} label={`${s.name} — ${s.domain}`} />
            ))}
          </Command.Group>
        </Command.List>
      </Command>
    </div>
  );
}

function PaletteItem({ onSelect, icon: Icon, label }: { onSelect: () => void; icon: React.ComponentType<{ className?: string }>; label: string }) {
  return (
    <Command.Item onSelect={onSelect} className="flex cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] text-fg aria-selected:bg-bg-subtle">
      <Icon className="size-4 text-fg-subtle" /> {label}
    </Command.Item>
  );
}
