# Lodestar — Agentic SEO operations

Lodestar audits a website, explains every issue with evidence, drafts fixes, and ships them
through WordPress, Shopify or GitHub **only after policy checks and approval** — then verifies the
live page, keeps an immutable audit trail, and can roll the change back.

> Product name and brand tokens live in `apps/web/lib/brand.ts` and `PRODUCT_NAME` (API).
> The spec this implements is `seo.pdf`. What is done, tested, needs credentials or is deferred:
> **[docs/completion-matrix.md](docs/completion-matrix.md)**.

## Quick start (local, no Docker, no paid credentials)

Requirements: Python 3.12+, Node 22+, PostgreSQL 16+ running locally.

```bash
make setup          # Python venv + npm install
make db             # create the runtime role aseo_app (RLS-enforced) and databases aseo, aseo_test
cp .env.example apps/api/.env
make migrate        # Alembic migrations (schema, RLS policies, append-only triggers)
make dev            # WordPress test fixture :8481 + API :8400 + web :3400
make seed           # in another terminal: demo users, demo site, first crawl, demo Search Console data
```

Open http://localhost:3400 and sign in:

| User | Password | What it shows |
|---|---|---|
| `demo@lodestar.example` | `demo-password-123` | Owner of *Northwind Coffee (Demo)* — a WordPress **fixture** site, audited, with fixes awaiting approval |
| `agency@lodestar.example` | `demo-password-123` | Agency owner with two client workspaces |
| `client@lodestar.example` | `demo-password-123` | Client user restricted to one workspace |

Demo mode is labelled everywhere (banner, "Fixture connector", "Demo data" badges). Writes in the
demo go to the local **WordPress companion-plugin test fixture**, not a real website.

With Docker instead: `docker compose up --build`, then `docker compose exec api python -m aseo.seed`.

## The core loop (M1)

Register site → verify ownership → connect WordPress → crawl → *Missing meta description* →
Execution Agent drafts a patch (AI or deterministic) → validation + policy → approve the exact
patch hash → execute → connector write → **re-read + live HTML verification** → before/after +
audit trail → rollback restores the previous value.

This loop is covered by `apps/api/tests/integration/test_m1_wordpress.py` (API) and
`apps/web/e2e/m1-flow.spec.ts` (browser).

## Tests

```bash
make test        # 88 backend tests: unit, integration, security, failure injection (PostgreSQL required)
make lint        # ruff + next lint
make typecheck   # TypeScript
make e2e         # Playwright against the running stack (uses installed Chrome; PW_CHANNEL=chromium for bundled)
scripts/backup_restore_check.sh aseo      # backup/restore drill
apps/api/.venv/bin/python scripts/loadtest.py   # read-path load test
```

## Real integrations

| Integration | Guide | Needs |
|---|---|---|
| WordPress | [docs/setup/wordpress.md](docs/setup/wordpress.md) | companion plugin + application password |
| Shopify | [docs/setup/shopify.md](docs/setup/shopify.md) | Admin API token or app credentials |
| GitHub (pull requests) | [docs/setup/github.md](docs/setup/github.md) | GitHub App |
| Google Search Console | [docs/setup/search-console.md](docs/setup/search-console.md) | OAuth client |
| Claude (AI) | [docs/setup/ai.md](docs/setup/ai.md) | `ANTHROPIC_API_KEY` |
| Billing | [docs/setup/billing.md](docs/setup/billing.md) | Stripe keys (test mode works without) |

Production never falls back to fixtures: fixture connectors and demo mode are refused when
`ENVIRONMENT=production`.

## Repository layout

```
apps/api/            FastAPI app, SQLAlchemy models, Alembic migrations, services, agents, tests
apps/worker/         Celery worker notes (worker code: apps/api/aseo/worker)
apps/web/            Next.js App Router UI (Tailwind, Radix/shadcn-style components, Recharts, Framer Motion), Playwright E2E
packages/contracts/  OpenAPI document + generated TypeScript types
integrations/wordpress/  Companion plugin + REST-contract test fixture
infra/db/            Runtime role bootstrap
docs/                Architecture, ADRs, threat model, capability matrix, setup guides, runbooks, SLOs, pilot checklist
scripts/             OpenAPI export, load test, backup/restore drill
```

## Documentation

[Architecture](docs/architecture.md) · [ADRs](docs/adr) · [Threat model](docs/security/threat-model.md) ·
[Connector capability matrix](docs/connectors/capability-matrix.md) · [Health score](docs/scoring.md) ·
[API](docs/api.md) · [Runbooks](docs/operations/runbooks.md) · [Deployment](docs/operations/deployment.md) ·
[SLOs & load test](docs/operations/slos-and-load-test.md) · [Pilot checklist](docs/pilot-checklist.md) ·
[Completion matrix](docs/completion-matrix.md)

## Honesty rules built into the product

No guaranteed rankings; the health score is an internal diagnostic, not a Google metric; Search
Console data is shown as delayed and incomplete with attribution caveats; search volume is never
estimated; AI content is draft-only; demo data and fixture connectors are always labelled.
