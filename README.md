# Lodestar — Agentic SEO SaaS (V1, in progress)

Spec: `seo.pdf`. Status: **backend + M1 WordPress vertical slice implemented and tested; web UI not yet built.**

## Run backend tests (local Postgres 16 + role)
```bash
psql -d postgres -f infra/db/init.sql && createdb aseo && createdb aseo_test
cd apps/api && python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # 78 tests: unit, M1 end-to-end, safety/security
.venv/bin/ruff check aseo tests migrations
```

## Run the API + WordPress fixture
```bash
cd apps/api && DATABASE_URL=postgresql+psycopg://localhost:5432/aseo .venv/bin/alembic upgrade head
.venv/bin/python ../../integrations/wordpress/fixture_server/server.py &      # labelled TEST FIXTURE on :8481
DATABASE_APP_URL=postgresql+psycopg://aseo_app:aseo_app_dev_password@localhost:5432/aseo \
CRAWLER_ALLOWED_PRIVATE_HOSTS='["127.0.0.1:8481"]' .venv/bin/uvicorn aseo.main:app --port 8400
# OpenAPI docs: http://localhost:8400/api/v1/docs
```

## Completion matrix
| Area | State |
|---|---|
| Models (49 tables), Alembic, RLS, append-only/immutable triggers | implemented, tested |
| Auth, orgs, RBAC, agency workspaces, CSRF, idempotency, rate limits | implemented, tested |
| SSRF-safe crawler, robots, sitemaps, rule engine, health score | implemented, tested |
| WordPress connector + companion plugin (`integrations/wordpress`) | implemented; tested against fixture; real site **requires credentials** |
| Change sets: hash-bound approval, policy, execute, live verify, rollback, kill switch | implemented, tested |
| AI gateway (Claude, deterministic fallback), 4 agents, copilot, workflows | implemented, tested (deterministic mode); LLM mode **requires ANTHROPIC_API_KEY** |
| Credits ledger, test billing webhooks, PDF reports, content drafts | implemented, tested |
| Typed TS contracts (`packages/contracts`) | generated |
| Next.js UI (`apps/web`: deps installed, no pages yet) | **deferred — next step** |
| Shopify / GitHub PR / Search Console connectors, Celery worker, Docker Compose, docs, E2E | **deferred** |
