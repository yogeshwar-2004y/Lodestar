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
