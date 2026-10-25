# ADR 0003 — PostgreSQL row-level security plus service-layer checks

**Status:** accepted

Every tenant-owned table has `ENABLE` + `FORCE ROW LEVEL SECURITY` with a policy on
`app.tenant_id` (a transaction-local GUC set from the authenticated session — never from request
bodies). The API connects as `aseo_app`, which is not a superuser and does not own the tables, so
policies apply. System jobs set `app.bypass_rls='on'` explicitly. Service-layer checks
(`Ctx.site()`, workspace scoping) remain the primary authorization; RLS is defence in depth and is
tested directly (`tests/integration/test_safety.py::test_tenant_isolation_api_and_rls`).
