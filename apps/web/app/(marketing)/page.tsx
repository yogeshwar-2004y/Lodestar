import {
  ArrowRight,
  Bot,
  Building2,
  CheckCircle2,
  FileSearch,
  GitPullRequest,
  History,
  LineChart,
  Lock,
  Rocket,
  ScanSearch,
  ShieldCheck,
  ShoppingBag,
  Store,
  Undo2,
  Users,
} from "lucide-react";
import Link from "next/link";

import { HeroWorkflow } from "@/components/marketing/hero-workflow";
import { Button } from "@/components/ui/button";
import { brand } from "@/lib/brand";

const steps = [
  { icon: ScanSearch, title: "Audit", body: "A polite, scoped crawler reads robots.txt, sitemaps, metadata, headings, links and structured data. Every issue keeps its evidence." },
  { icon: Bot, title: "Explain & plan", body: "Four specialised agents group findings, cite the evidence they used, and prioritise by severity, reach and effort." },
  { icon: FileSearch, title: "Propose a fix", body: "Drafts become immutable patches with a before/after diff, validation results and a risk score." },
  { icon: ShieldCheck, title: "Approve", body: "Policy decides what needs a human. Approvals bind to the exact patch — any edit invalidates them." },
  { icon: Rocket, title: "Ship & verify", body: "Changes go through your platform's API (or a GitHub pull request), then we re-read the live page to confirm." },
  { icon: Undo2, title: "Roll back", body: "Previous values are snapshotted before every write. Restore in one click where the platform supports it." },
];

const platforms = [
  { icon: Store, name: "WordPress", body: "Companion plugin with least-privilege role, revision history and conflict detection. Works with Yoast, Rank Math or standalone." },
  { icon: ShoppingBag, name: "Shopify", body: "Authorized app using the Admin GraphQL API for product, collection and page SEO fields. Theme edits stay review-only." },
  { icon: GitPullRequest, name: "GitHub", body: "A GitHub App opens a branch and pull request with the diff. Never pushes to your default branch. Verified after deploy." },
  { icon: FileSearch, name: "Any public site", body: "Read-only audits and recommendations for sites you can't connect. We never claim write access we don't have." },
];

const faqs = [
  ["Will this improve my rankings?", "We can't promise that, and nobody honestly can. We fix verifiable technical and on-page issues, measure what changed on your site, and show search data with clear caveats about delays, sampling and seasonality."],
  ["Can the AI change my site on its own?", "Not by default. New sites start in Assist mode, where every change needs a human approval. Autopilot is opt-in, limited to low-risk metadata in paths you choose, with daily caps, and every auto-change is logged and reversible."],
  ["What does the health score mean?", "It's an internal diagnostic that summarises the issues we found using a documented weighting. It is not a Google score and doesn't predict rankings."],
  ["Does AI-written content get published automatically?", "Never. Content Studio produces briefs and drafts for your editors. Publishing requires explicit editorial approval and is done by you."],
  ["How are my credentials stored?", "Connector secrets are encrypted and stored by reference, never shown again, never sent to AI models and never written to logs or audit events. You can revoke them any time."],
  ["Can agencies manage client sites?", "Yes. Agency workspaces separate clients, give client users access only to their own sites, and produce branded PDF reports."],
];

export default function Landing() {
  return (
    <>
      {/* hero */}
      <section className="relative overflow-hidden">
        <div className="bg-grid pointer-events-none absolute inset-0 opacity-[0.35] [mask-image:radial-gradient(ellipse_at_top,black_30%,transparent_70%)]" aria-hidden />
        <div className="pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[920px] -translate-x-1/2 rounded-full bg-gradient-to-br from-accent/20 via-teal/10 to-transparent blur-3xl" aria-hidden />
        <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-4 pt-16 pb-20 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:pt-24">
          <div>
            <p className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-xs text-fg-muted shadow-sm">
              <span className="size-1.5 rounded-full bg-teal" aria-hidden /> Agentic SEO, with a human in the loop
            </p>
            <h1 className="mt-5 font-display text-[44px] leading-[1.02] tracking-tight text-balance sm:text-6xl">
              SEO fixes that ship themselves — <em className="text-accent">only after you say yes.</em>
            </h1>
            <p className="mt-5 max-w-xl text-[17px] leading-relaxed text-fg-muted">{brand.description}</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild size="lg">
                <Link href="/signup">
                  Start free trial <ArrowRight />
                </Link>
              </Button>
              <Button asChild size="lg" variant="secondary">
                <a href="#how">See how it works</a>
              </Button>
            </div>
            <ul className="mt-8 grid max-w-lg gap-2 text-sm text-fg-muted sm:grid-cols-2">
              {["Evidence behind every issue", "Approval bound to the exact change", "Live verification after every write", "One-click rollback where supported"].map((t) => (
                <li key={t} className="flex items-center gap-2">
                  <CheckCircle2 className="size-4 text-teal" aria-hidden /> {t}
                </li>
              ))}
            </ul>
          </div>
          <HeroWorkflow />
        </div>
      </section>

      {/* how it works */}
      <section id="how" className="border-y border-border bg-surface/60 py-20">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <p className="text-sm font-medium text-accent">How it works</p>
          <h2 className="mt-2 max-w-2xl font-display text-4xl tracking-tight">From finding to verified fix, with a paper trail at every step.</h2>
          <ol className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {steps.map((s, i) => (
              <li key={s.title} className="group rounded-2xl border border-border bg-surface p-6 shadow-card transition-transform hover:-translate-y-0.5">
                <div className="flex items-center gap-3">
                  <span className="grid size-10 place-items-center rounded-xl bg-accent-soft text-accent">
                    <s.icon className="size-5" aria-hidden />
                  </span>
                  <span className="font-mono text-xs text-fg-subtle">0{i + 1}</span>
                </div>
                <h3 className="mt-4 text-lg font-semibold">{s.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-fg-muted">{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* platforms */}
      <section id="platforms" className="py-20">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <div className="grid gap-10 lg:grid-cols-[1fr_1.4fr]">
            <div>
              <p className="text-sm font-medium text-accent">Supported platforms</p>
              <h2 className="mt-2 font-display text-4xl tracking-tight">Real integrations, honest capabilities.</h2>
              <p className="mt-4 text-fg-muted">
                Each connector declares exactly which changes it can make, whether it can roll them back, and which permissions it needs. Anything it
                can&apos;t do stays a recommendation.
              </p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {platforms.map((p) => (
                <div key={p.name} className="rounded-2xl border border-border bg-surface p-5 shadow-card">
                  <p.icon className="size-5 text-teal" aria-hidden />
                  <h3 className="mt-3 font-semibold">{p.name}</h3>
                  <p className="mt-1 text-sm text-fg-muted">{p.body}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* safety */}
      <section id="safety" className="relative overflow-hidden bg-[#111216] py-20 text-[#ecebe8]">
        <div className="pointer-events-none absolute right-0 top-0 h-80 w-80 rounded-full bg-accent/25 blur-3xl" aria-hidden />
        <div className="relative mx-auto max-w-6xl px-4 sm:px-6">
          <p className="text-sm font-medium text-[#a5a2ff]">Security & approvals</p>
          <h2 className="mt-2 max-w-2xl font-display text-4xl tracking-tight">Automation you can audit, pause and undo.</h2>
          <div className="mt-12 grid gap-6 md:grid-cols-3">
            {[
              { icon: Lock, t: "Policy before power", b: "Observe, Assist or Autopilot per site. Canonical, robots, redirect and bulk changes are never automated. AI confidence can't authorize a write." },
              { icon: History, t: "Immutable history", b: "Patches are hashed and immutable. Approvals bind to the hash. Every action lands in a tamper-evident, append-only audit log." },
              { icon: ShieldCheck, t: "Built-in brakes", b: "An organization-wide kill switch, per-site pause, daily limits, conflict detection and automatic retries with dead-letter alerts." },
            ].map((x) => (
              <div key={x.t} className="rounded-2xl border border-white/10 bg-white/[0.03] p-6">
                <x.icon className="size-5 text-[#3cc7b7]" aria-hidden />
                <h3 className="mt-3 font-semibold">{x.t}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-[#a7a49e]">{x.b}</p>
              </div>
            ))}
          </div>
          <p className="mt-8 text-sm text-[#a7a49e]">
            Tenant data is isolated in the database itself (row-level security), connector secrets are encrypted by reference, and crawled pages are
            treated as untrusted data — never as instructions to our agents.
          </p>
        </div>
      </section>

      {/* use cases */}
      <section className="py-20">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <h2 className="font-display text-4xl tracking-tight">Made for teams who answer for their website.</h2>
          <div className="mt-10 grid gap-5 md:grid-cols-3">
            {[
              { icon: Store, t: "Small businesses", b: "Find and fix the basics without hiring an agency. Approve changes from your inbox in seconds." },
              { icon: LineChart, t: "SaaS teams", b: "Ship metadata fixes as GitHub pull requests that go through your normal review and deploy pipeline." },
              { icon: Building2, t: "Agencies", b: "Separate client workspaces, client-safe roles, branded reports and one approval inbox across every site." },
            ].map((u) => (
              <div key={u.t} className="rounded-2xl border border-border bg-surface p-6 shadow-card">
                <u.icon className="size-5 text-accent" aria-hidden />
                <h3 className="mt-3 text-lg font-semibold">{u.t}</h3>
                <p className="mt-1.5 text-sm text-fg-muted">{u.b}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* pricing teaser */}
      <section className="border-y border-border bg-surface/60 py-16">
        <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-6 px-4 sm:px-6 md:flex-row md:items-center">
          <div>
            <h2 className="font-display text-3xl tracking-tight">Simple plans plus metered AI credits.</h2>
            <p className="mt-2 text-fg-muted">Pay for the sites you manage. Crawls and AI work draw on a transparent credit balance.</p>
          </div>
          <Button asChild variant="secondary" size="lg">
            <Link href="/pricing">
              <Users /> Compare plans
            </Link>
          </Button>
        </div>
      </section>

      {/* faq */}
      <section id="faq" className="py-20">
        <div className="mx-auto max-w-3xl px-4 sm:px-6">
          <h2 className="font-display text-4xl tracking-tight">Questions, answered plainly.</h2>
          <div className="mt-8 divide-y divide-border rounded-2xl border border-border bg-surface">
            {faqs.map(([q, a]) => (
              <details key={q} className="group px-5 py-4">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium">
                  {q}
                  <span className="text-fg-subtle transition-transform group-open:rotate-45" aria-hidden>+</span>
                </summary>
                <p className="mt-2 text-sm leading-relaxed text-fg-muted">{a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* cta */}
      <section className="pb-24">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <div className="relative overflow-hidden rounded-3xl border border-border bg-gradient-to-br from-accent to-[#2c2a8c] px-8 py-14 text-white shadow-xl">
            <div className="pointer-events-none absolute -right-10 -bottom-20 size-72 rounded-full bg-teal/40 blur-3xl" aria-hidden />
            <h2 className="relative max-w-xl font-display text-4xl tracking-tight">Run your first audit in minutes.</h2>
            <p className="relative mt-3 max-w-lg text-white/80">Connect a site, see every issue with evidence, and approve your first verified fix.</p>
            <Button asChild size="lg" variant="secondary" className="relative mt-7 border-white/20 bg-white text-[#1b1a18] hover:bg-white/90">
              <Link href="/signup">
                Start free trial <ArrowRight />
              </Link>
            </Button>
          </div>
        </div>
      </section>
    </>
  );
}
