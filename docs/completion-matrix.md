# Completion matrix

Legend: **implemented** — code exists; **tested** — automated tests exercise it (unit/integration/E2E);
**requires credentials** — works only with real third-party credentials not available here;
**deferred** — not built yet.

| Area | Status | Evidence |
|---|---|---|
| Auth (sessions, CSRF, argon2), orgs, memberships, RBAC (owner/admin/editor/analyst/viewer/client) | implemented, tested | `test_safety.py` (RBAC, CSRF), E2E sign-up |
| Tenant isolation (service layer + PostgreSQL RLS as non-owner role) | implemented, tested | `test_tenant_isolation_api_and_rls` |
| Agency workspaces, client roles, branded PDF reports | implemented, tested | `test_agency_client_workspace_boundary`, `test_reports_and_plan`, E2E boundaries |
| Site registration, ownership verification (plugin token, meta, DNS TXT, file, platform domain match) | implemented; plugin path tested; DNS/meta/file need a public site | `wp_site` fixture |
| SSRF-safe crawler: robots, sitemaps (+index, gzip, XXE-safe), scope, caps, throttling, redirects | implemented, tested | `tests/unit/*` |
| JS rendering (Playwright workers) | deferred — pages needing JS are flagged by a heuristic rule | `js_rendering_required` |
| Rule engine (27 rules, deterministic vs heuristic), internal health score | implemented, tested | `test_crawler_rules.py`, `docs/scoring.md` |
| PageSpeed Insights / CrUX | deferred | — |
| Change sets: immutable versions, hash-bound approvals, policy, execution, verification, rollback, kill switch, locks, retries, dead letters | implemented, tested | `test_m1_wordpress.py`, `test_safety.py` |
| WordPress companion plugin + connector | implemented; tested against the REST-contract fixture; **real WordPress requires credentials** | `integrations/wordpress` |
| Shopify connector, OAuth, webhooks | implemented; tested against an API fake; **requires credentials** for a real store | `test_connectors_platforms.py` |
| GitHub App PR connector, webhooks | implemented; tested against an API fake; **requires a GitHub App** | `test_connectors_platforms.py` |
| Search Console OAuth + sync | implemented; demo fixture tested; **real sync requires Google credentials** | `test_gsc_demo_sync_is_labelled` |
| GA4 connector | deferred | — |
| Paid keyword provider | deferred (abstraction documented; volume never estimated) | — |
| AI gateway (Claude, structured outputs, refusal fallback, cost accounting), deterministic fallback | implemented; deterministic path tested; **LLM path requires ANTHROPIC_API_KEY** (not exercised here) | `ai/gateway.py` |
| Audit / Strategy / Execution / Measurement agents, Copilot, persisted workflows, tool invocation logs | implemented, tested (deterministic mode) | `test_m1_end_to_end`, `test_copilot_grounded_with_citations` |
| Prompt-injection controls | implemented, tested | `test_prompt_injection_page_content_is_data` |
| Content Studio (briefs, drafts, editorial approval; no auto-publish) | implemented; UI verified manually | — |
| Internal-link / structured-data fix workflows | recommendation-only in V1 (review-first); automated edits deferred | capability matrix |
| AI-search visibility beta | deferred | — |
| Billing: plans, quotas, append-only credit ledger, test provider, signed webhooks; Stripe adapter | implemented; test provider tested; **Stripe requires credentials** | `test_ledger_webhooks_ai.py` |
| Notifications (in-app) | implemented; email delivery deferred | — |
| Scheduled & event-driven crawls, outbox, Celery worker + beat | implemented; worker smoke-tested locally | `docs/architecture.md` |
| Retention & deletion jobs, data export | implemented, tested | `test_retention.py` |
| Backup/restore drill | implemented, run locally (passed) | `scripts/backup_restore_check.sh` |
| Web app (all 16 required screens, design system, light/dark, responsive, command palette) | implemented; build + typecheck + lint pass; E2E covers core flows | `apps/web`, `e2e/*` |
| E2E (Playwright: onboarding → audit → approve → execute → verify → rollback, boundaries, a11y/responsive smoke) | implemented, passing locally against installed Chrome | `apps/web/e2e` |
| Docker Compose, Dockerfiles | implemented; compose config validated; full image build not run here (disk space) | `docker-compose.yml` |
| CI workflow | implemented (not yet run on GitHub) | `.github/workflows/ci.yml` |
| OpenTelemetry tracing | dependency present; exporter wiring deferred | — |
| MFA / SSO, email verification | deferred | threat model |
| Load test | run locally; results documented | `docs/operations/slos-and-load-test.md` |
