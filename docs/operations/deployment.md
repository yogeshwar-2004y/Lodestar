# Deployment (pilot)

Recommended AWS layout, sized for a bounded pilot (actual cost depends on usage; not guaranteed):

| Component | Service | Pilot size |
|---|---|---|
| API | ECS Fargate service behind an ALB (HTTPS) | 2 tasks × 0.5 vCPU / 1 GB |
| Worker + beat | ECS Fargate services (beat: exactly 1 task) | 1–2 × 0.5 vCPU / 1 GB, 1 × 0.25 vCPU |
| Web | ECS Fargate or Vercel | 1–2 tasks |
| Database | RDS PostgreSQL 16, Multi-AZ optional | db.t4g.small, 20 GB gp3, PITR on |
| Redis | ElastiCache (cache.t4g.micro) | broker + rate-limit counters |
| Storage | S3 (`STORAGE_BACKEND=s3`), versioning on | |
| Secrets | Secrets Manager (`SECRETS_BACKEND=aws`) + KMS | |
| Egress | NAT gateway; security groups deny RFC1918 egress except RDS/Redis | defence in depth for SSRF |
| Observability | CloudWatch logs (JSON), OpenTelemetry collector, optional Sentry | |

Steps: build images (`apps/api/Dockerfile`, `apps/web/Dockerfile`); run `alembic upgrade head` as the
owner role (one-off task); create `aseo_app` with `infra/db/init.sql` and a strong password; set
`ENVIRONMENT=production`, `DEMO_MODE=false`, `COOKIE_SECURE=true`, `SECRET_KEY`,
`SECRETS_ENCRYPTION_KEY` (or `SECRETS_BACKEND=aws`), `DATABASE_URL` (owner, migrations only) and
`DATABASE_APP_URL` (runtime). The app refuses to start in production with demo mode, a dev secret,
insecure cookies or a crawler private-host allowlist.

## Render (demo / staging)

`render.yaml` is a Render Blueprint: **Dashboard → New → Blueprint → pick this repo → Apply**. It creates:

| Resource | Purpose |
|---|---|
| `lodestar-db` (PostgreSQL 16, free) | database; migrations run on API start (`apps/api/start.sh`) |
| `lodestar-api` (Docker, free) | FastAPI + in-process job relay (`TASK_EXECUTION=inline`); seeds demo users once (`SEED_DEMO=true`) |
| `lodestar-web` (Docker, free) | Next.js; proxies `/api/v1` to the API (URL baked in at build time) |
| `lodestar-wp-fixture` (Docker, free) | labelled WordPress companion-plugin test fixture for the demo; control endpoints require `FIXTURE_CONTROL_TOKEN` |

Notes: free services sleep after inactivity (first request can take ~1 minute) and the free database
expires after 30 days. The runtime uses the database owner role; `FORCE ROW LEVEL SECURITY` still
applies to it (only superusers/BYPASSRLS roles skip RLS). For a real pilot: paid plans, a separate
non-owner `DATABASE_APP_URL` role, Redis + a worker service, `ENVIRONMENT=production`, `DEMO_MODE=false`,
`SECRETS_ENCRYPTION_KEY`, and remove the fixture service.
