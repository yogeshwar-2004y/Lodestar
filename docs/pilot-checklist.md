# Pilot checklist

## Before onboarding a pilot customer
- [ ] Production config: `ENVIRONMENT=production`, `DEMO_MODE=false`, `COOKIE_SECURE=true`, strong `SECRET_KEY`, `SECRETS_ENCRYPTION_KEY`/AWS secrets
- [ ] Runtime DB role is `aseo_app` (non-owner) — verify `select rolsuper, rolbypassrls from pg_roles where rolname='aseo_app'` is `f, f`
- [ ] Backups + PITR enabled; `scripts/backup_restore_check.sh` run against a restored snapshot
- [ ] Egress firewall blocks private ranges; WAF in front of the ALB
- [ ] Alerts configured (see runbooks)
- [ ] AI provider key set (or deliberately deterministic) and credit pricing reviewed
- [ ] Plans/prices edited in `plans`; billing provider configured or test mode communicated

## M1 acceptance on an owned WordPress staging site
- [ ] Install the companion plugin; create the *Lodestar SEO Agent* user + application password
- [ ] Register site → verify via plugin token → connect (live mode)
- [ ] Crawl → confirm "Missing meta description" with the correct affected URLs
- [ ] Draft (AI or deterministic) → review diff → approve the hash → execute
- [ ] Confirm "Verified in live HTML" shows the new value; view the page source yourself
- [ ] Before/after and audit trail present; audit chain verifies
- [ ] Roll back → the previous value is live again; finding re-opens
- [ ] Edit the field in WordPress between approval and execution → execution refuses (stale version)

## V1 pilot acceptance
- [ ] Shopify: product SEO description update verified on the storefront (test store)
- [ ] GitHub: PR opened against the site repo; after merge+deploy the change verifies; base branch never written directly
- [ ] Agency: client user sees only their workspace; branded PDF report generated
- [ ] Search Console connected; performance chart shows real data with caveats; annotations appear
- [ ] Billing metering: ledger reconciles; budget exhaustion blocks crawls
- [ ] Kill switch drill: engage, confirm queued executions cancelled, release
- [ ] Load test repeated on pilot infrastructure; SLO dashboard live
