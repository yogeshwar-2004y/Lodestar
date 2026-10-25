"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Copy, FileCode2, GitPullRequest, Globe, KeyRound, Radar, ShoppingBag, Store } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, CardBody, CardHeader, Field, Input, Stepper, Switch, Textarea } from "@/components/ui/core";
import { ApiError, http, newIdempotencyKey } from "@/lib/api";
import { type Site, useMeta } from "@/lib/hooks";
import { cn } from "@/lib/utils";

const STEPS = ["Domain", "Ownership", "Platform", "Permissions", "Crawl settings", "First audit"];
const PLATFORMS = [
  { key: "wordpress", label: "WordPress", icon: Store, note: "Companion plugin + application password" },
  { key: "shopify", label: "Shopify", icon: ShoppingBag, note: "Authorized app (Admin API)" },
  { key: "github", label: "GitHub", icon: GitPullRequest, note: "GitHub App → pull requests" },
  { key: "public", label: "Any site (read-only)", icon: Globe, note: "Audit & recommendations only" },
] as const;

type Capability = { action_type: string; supported: boolean; write_mode: string; rollback_supported: boolean; permissions: string[]; notes: string | null };
type Connector = { id: string; provider: string; status: string; mode: string; last_error: string | null; capabilities: Capability[] };

export default function NewSite() {
  const router = useRouter();
  const qc = useQueryClient();
  const meta = useMeta();
  const [step, setStep] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [site, setSite] = React.useState<Site | null>(null);
  const [platform, setPlatform] = React.useState<(typeof PLATFORMS)[number]["key"]>("wordpress");
  const [verification, setVerification] = React.useState<{ method: string; token: string; instructions: { steps: string[]; value: string } } | null>(null);
  const [verified, setVerified] = React.useState(false);
  const [connector, setConnector] = React.useState<Connector | null>(null);
  const [fixture, setFixture] = React.useState(false);
  const [crawl, setCrawl] = React.useState({ max_pages: 100, include: "", exclude: "", respect_robots: true });

  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong");

  async function createSite(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      const s = await http<Site>("/sites", { json: { name: f.get("name"), url: f.get("url"), platform, business_goals: f.get("goals") || null } });
      setSite(s);
      qc.invalidateQueries({ queryKey: ["sites"] });
      setStep(1);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function startVerification(method: string) {
    if (!site) return;
    setBusy(true);
    try {
      const r = await http<{ token: string; instructions: { steps: string[]; value: string } }>(`/sites/${site.id}/verification/start`, { json: { method } });
      setVerification({ method, token: r.token, instructions: r.instructions });
      if (method === "connector") setStep(2);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function checkVerification() {
    if (!site) return;
    setBusy(true);
    try {
      const v = await http<{ status: string; evidence: Record<string, unknown> }>(`/sites/${site.id}/verification/check`, { method: "POST" });
      if (v.status === "verified") {
        setVerified(true);
        toast.success("Ownership verified");
        if (step === 1) setStep(2);
      } else toast.warning("Not verified yet — the token wasn't found. Check the instructions and try again.");
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function connect(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!site) return;
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      const body =
        platform === "wordpress"
          ? { provider: "wordpress", mode: fixture ? "fixture" : "live", config: { username: f.get("username"), rest_url: f.get("rest_url") || undefined }, secrets: { app_password: String(f.get("app_password") ?? "") } }
          : platform === "shopify"
            ? { provider: "shopify", config: { shop: f.get("shop") }, secrets: { access_token: String(f.get("access_token") ?? "") } }
            : { provider: "github", config: { owner: f.get("owner"), repo: f.get("repo"), base_branch: f.get("base_branch") || "main", installation_id: f.get("installation_id"), framework: f.get("framework") } };
      const c = await http<Connector>(`/sites/${site.id}/connectors`, { json: body });
      setConnector(c);
      if (c.status === "connected") {
        toast.success("Connected");
        setStep(3);
      } else toast.error(c.last_error ?? "Connection failed");
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function saveCrawlAndAudit() {
    if (!site) return;
    setBusy(true);
    try {
      const split = (v: string) => v.split(",").map((s) => s.trim()).filter(Boolean);
      await http(`/sites/${site.id}`, { method: "PATCH", json: { crawl_settings: { max_pages: crawl.max_pages, include_paths: split(crawl.include), exclude_paths: split(crawl.exclude), respect_robots: crawl.respect_robots } } });
      await http(`/sites/${site.id}/crawls`, { json: {}, idempotencyKey: newIdempotencyKey("first-crawl") });
      toast.success("First audit queued");
      router.push(`/app/sites/${site.id}?welcome=1`);
    } catch (err) {
      fail(err);
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Add a website" description="Connect a site, prove you own it, and run the first audit. Writes are only ever possible on verified sites." />
      <Card className="mb-6 px-5 py-4">
        <Stepper steps={STEPS} current={step} />
      </Card>

      {step === 0 && (
        <Card>
          <CardHeader title="Website" description="Which site should we audit?" />
          <CardBody>
            <form onSubmit={createSite} className="space-y-5">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Name" htmlFor="name">
                  <Input id="name" name="name" required placeholder="Northwind Coffee" />
                </Field>
                <Field label="Domain or URL" htmlFor="url" hint="e.g. northwind.example or https://shop.northwind.example">
                  <Input id="url" name="url" required placeholder="https://" />
                </Field>
              </div>
              <fieldset>
                <legend className="mb-2 text-[13px] font-medium">Platform</legend>
                <div className="grid gap-3 sm:grid-cols-2">
                  {PLATFORMS.map((p) => (
                    <label key={p.key} className={cn("flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 transition-colors", platform === p.key ? "border-accent bg-accent-soft/40 ring-1 ring-accent/30" : "border-border hover:border-border-strong")}>
                      <input type="radio" className="sr-only" name="platform" value={p.key} checked={platform === p.key} onChange={() => setPlatform(p.key)} />
                      <p.icon className="mt-0.5 size-5 text-accent" aria-hidden />
                      <span>
                        <span className="block text-[14px] font-medium">{p.label}</span>
                        <span className="text-[12.5px] text-fg-muted">{p.note}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <Field label="Business goals (optional)" htmlFor="goals" hint="Helps the Strategy Agent prioritise. e.g. “Grow subscription sign-ups in the US”.">
                <Textarea id="goals" name="goals" maxLength={2000} />
              </Field>
              <Button type="submit" loading={busy}>Continue</Button>
            </form>
          </CardBody>
        </Card>
      )}

      {step === 1 && site && (
        <Card>
          <CardHeader title="Verify ownership" description="We never write to — or automatically change — a site whose ownership isn't verified." />
          <CardBody className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-2">
              {[
                ...(platform === "wordpress" ? [{ m: "connector", icon: KeyRound, t: "Via the WordPress plugin", d: "Paste a token in Settings → Lodestar. Recommended." }] : []),
                { m: "meta_tag", icon: FileCode2, t: "HTML meta tag", d: "Add a tag to your homepage <head>." },
                { m: "dns_txt", icon: Globe, t: "DNS TXT record", d: "Add a TXT record at your DNS provider." },
                { m: "well_known_file", icon: FileCode2, t: "Verification file", d: "Upload a file to /.well-known/." },
              ].map((o) => (
                <button key={o.m} onClick={() => startVerification(o.m)} disabled={busy} className={cn("flex items-start gap-3 rounded-xl border p-3.5 text-left transition-colors hover:border-border-strong", verification?.method === o.m ? "border-accent ring-1 ring-accent/30" : "border-border")}>
                  <o.icon className="mt-0.5 size-5 text-teal" aria-hidden />
                  <span>
                    <span className="block text-[14px] font-medium">{o.t}</span>
                    <span className="text-[12.5px] text-fg-muted">{o.d}</span>
                  </span>
                </button>
              ))}
            </div>
            {verification && verification.method !== "connector" && (
              <Instructions v={verification} onCheck={checkVerification} busy={busy} />
            )}
            {platform === "public" && (
              <Button variant="ghost" onClick={() => setStep(4)}>Skip for now — read-only audit</Button>
            )}
          </CardBody>
        </Card>
      )}

      {step === 2 && site && (
        <Card>
          <CardHeader title="Connect your platform" description="Credentials are encrypted and stored by reference. They are never shown again, sent to AI models, or logged." />
          <CardBody className="space-y-5">
            {platform === "public" ? (
              <Alert tone="info" title="Read-only site">No connector needed. Changes will be shown as recommendations you apply yourself.</Alert>
            ) : (
              <form onSubmit={connect} className="space-y-4">
                {platform === "wordpress" && (
                  <>
                    <ol className="list-decimal space-y-1 pl-5 text-[13px] text-fg-muted">
                      <li>Install and activate the <b>Lodestar Companion</b> plugin (integrations/wordpress).</li>
                      <li>Create a user with the <b>Lodestar SEO Agent</b> role and generate an Application Password for it.</li>
                      {verification?.method === "connector" && (
                        <li>
                          In WordPress → Settings → Lodestar, paste this token: <CopyValue value={verification.token} />
                        </li>
                      )}
                    </ol>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <Field label="WordPress username" htmlFor="username">
                        <Input id="username" name="username" required defaultValue={fixture ? "lodestar-agent" : ""} />
                      </Field>
                      <Field label="Application password" htmlFor="app_password">
                        <Input id="app_password" name="app_password" type="password" required autoComplete="off" defaultValue={fixture ? "fixture-app-password" : ""} key={String(fixture)} />
                      </Field>
                    </div>
                    <Field label="REST API URL (optional)" htmlFor="rest_url" hint="Defaults to <site>/wp-json/">
                      <Input id="rest_url" name="rest_url" placeholder="https://example.com/wp-json/" />
                    </Field>
                    {meta.data?.demo_mode && (
                      <div className="flex items-center justify-between rounded-xl border border-warning/30 bg-warning-soft px-4 py-3">
                        <div className="text-[13px]">
                          <p className="font-medium text-fg">Use the local WordPress test fixture</p>
                          <p className="text-fg-muted">Demo mode only. Writes go to the fixture server and are labelled “Fixture” everywhere.</p>
                        </div>
                        <Switch checked={fixture} onCheckedChange={setFixture} label="Use WordPress test fixture" />
                      </div>
                    )}
                  </>
                )}
                {platform === "shopify" && (
                  <>
                    <Field label="Shop domain" htmlFor="shop" hint="your-store.myshopify.com">
                      <Input id="shop" name="shop" required pattern="[a-z0-9-]+\.myshopify\.com" />
                    </Field>
                    <Field label="Admin API access token" htmlFor="access_token" hint="From your custom app (scopes: read/write_products, read/write_content), or use OAuth below.">
                      <Input id="access_token" name="access_token" type="password" autoComplete="off" required />
                    </Field>
                    {meta.data?.integrations.shopify && (
                      <Button type="button" variant="secondary" onClick={() => (window.location.href = `/api/v1/integrations/shopify/authorize?site_id=${site.id}`)}>Install via OAuth instead</Button>
                    )}
                  </>
                )}
                {platform === "github" && (
                  <>
                    {!meta.data?.integrations.github && <Alert tone="warning" title="GitHub App not configured">Set GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY on the server (see docs/setup/github.md).</Alert>}
                    <div className="grid gap-4 sm:grid-cols-3">
                      <Field label="Owner" htmlFor="owner"><Input id="owner" name="owner" required /></Field>
                      <Field label="Repository" htmlFor="repo"><Input id="repo" name="repo" required /></Field>
                      <Field label="Base branch" htmlFor="base_branch"><Input id="base_branch" name="base_branch" defaultValue="main" /></Field>
                    </div>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <Field label="Installation ID" htmlFor="installation_id"><Input id="installation_id" name="installation_id" required /></Field>
                      <Field label="Framework mapping" htmlFor="framework" hint="static-html, markdown-frontmatter">
                        <Input id="framework" name="framework" defaultValue="markdown-frontmatter" />
                      </Field>
                    </div>
                  </>
                )}
                <Button type="submit" loading={busy}>Connect</Button>
              </form>
            )}
            {connector && connector.status !== "connected" && <Alert tone="danger" title="Connection failed">{connector.last_error}</Alert>}
            {platform === "public" && <Button onClick={() => setStep(4)}>Continue</Button>}
          </CardBody>
        </Card>
      )}

      {step === 3 && site && connector && (
        <Card>
          <CardHeader title="Permissions & capabilities" description="Exactly what this connector can and can't do. Anything unsupported stays a recommendation." />
          <CardBody className="space-y-5">
            <ul className="divide-y divide-border rounded-xl border border-border">
              {connector.capabilities.map((c) => (
                <li key={c.action_type} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
                  <div>
                    <p className="font-mono text-[13px]">{c.action_type}</p>
                    {c.notes && <p className="text-[12px] text-fg-muted">{c.notes}</p>}
                  </div>
                  <div className="flex gap-1.5">
                    {c.supported ? <Badge tone="success">Can write · {c.write_mode}</Badge> : <Badge>Recommendation only</Badge>}
                    {c.supported && (c.rollback_supported ? <Badge tone="teal">Rollback</Badge> : <Badge tone="warning">No auto-rollback</Badge>)}
                  </div>
                </li>
              ))}
            </ul>
            {!verified && verification?.method === "connector" && (
              <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border p-4">
                <p className="flex-1 text-[13px] text-fg-muted">Now that the plugin is connected, confirm the verification token you pasted into WordPress.</p>
                <Button onClick={checkVerification} loading={busy}>Check verification</Button>
              </div>
            )}
            {verified && <Alert tone="success" title="Ownership verified" />}
            <Button onClick={() => setStep(4)} disabled={!verified && platform !== "public"}>Continue</Button>
          </CardBody>
        </Card>
      )}

      {step === 4 && site && (
        <Card>
          <CardHeader title="Crawl settings" description="We crawl politely: robots.txt honoured, throttled, same-site only, capped by your plan." />
          <CardBody className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Max pages" htmlFor="max_pages">
                <Input id="max_pages" type="number" min={1} max={10000} value={crawl.max_pages} onChange={(e) => setCrawl({ ...crawl, max_pages: Number(e.target.value) })} />
              </Field>
              <Field label="Only these paths" htmlFor="include" hint="Comma-separated, e.g. /blog">
                <Input id="include" value={crawl.include} onChange={(e) => setCrawl({ ...crawl, include: e.target.value })} />
              </Field>
              <Field label="Exclude paths" htmlFor="exclude" hint="e.g. /cart, /account">
                <Input id="exclude" value={crawl.exclude} onChange={(e) => setCrawl({ ...crawl, exclude: e.target.value })} />
              </Field>
            </div>
            <label className="flex items-center gap-3 text-[13px]">
              <Switch checked={crawl.respect_robots} onCheckedChange={(v) => setCrawl({ ...crawl, respect_robots: v })} label="Respect robots.txt" /> Respect robots.txt (recommended)
            </label>
            <Button onClick={() => setStep(5)}>Continue</Button>
          </CardBody>
        </Card>
      )}

      {step === 5 && site && (
        <Card>
          <CardHeader title="Run the first audit" description="The crawl runs in the background. Audit and Strategy agents will summarise the results when it finishes." />
          <CardBody>
            <ul className="mb-5 space-y-2 text-[13.5px]">
              <li className="flex items-center gap-2"><CheckCircle2 className="size-4 text-success" /> {site.domain} registered</li>
              <li className="flex items-center gap-2"><CheckCircle2 className={cn("size-4", verified ? "text-success" : "text-fg-subtle")} /> Ownership {verified ? "verified" : "not verified (read-only)"}</li>
              <li className="flex items-center gap-2"><CheckCircle2 className={cn("size-4", connector?.status === "connected" ? "text-success" : "text-fg-subtle")} /> {connector ? `${connector.provider} connected (${connector.mode})` : "No connector"}</li>
            </ul>
            <Button size="lg" onClick={saveCrawlAndAudit} loading={busy}>
              <Radar /> Start first audit
            </Button>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

function CopyValue({ value }: { value: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-bg-subtle px-2 py-0.5 font-mono text-[12px] text-fg">
      {value}
      <button type="button" onClick={() => { navigator.clipboard.writeText(value); toast.success("Copied"); }} aria-label="Copy" className="text-fg-subtle hover:text-fg">
        <Copy className="size-3.5" />
      </button>
    </span>
  );
}

function Instructions({ v, onCheck, busy }: { v: { instructions: { steps: string[]; value: string } }; onCheck: () => void; busy: boolean }) {
  return (
    <div className="rounded-xl border border-border bg-surface-2 p-4">
      {v.instructions.steps.map((s) => <p key={s} className="text-[13px] text-fg-muted">{s}</p>)}
      <pre className="mt-2 overflow-x-auto rounded-lg bg-bg-subtle p-3 font-mono text-[12px]">{v.instructions.value}</pre>
      <div className="mt-3 flex gap-2">
        <Button variant="secondary" size="sm" onClick={() => { navigator.clipboard.writeText(v.instructions.value); toast.success("Copied"); }}><Copy /> Copy</Button>
        <Button size="sm" onClick={onCheck} loading={busy}>Check now</Button>
      </div>
    </div>
  );
}
