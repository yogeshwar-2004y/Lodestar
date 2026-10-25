# Architecture

Lodestar is a **modular monolith** (FastAPI) with **background workers** (Celery, or an
in-process relay for single-command local runs) and a **Next.js** web app.

```
 Browser ──► Next.js (apps/web, :3400) ──/api/v1 proxy──► FastAPI (apps/api, :8400)
                                                              │
                     ┌────────────────────────────────────────┼─────────────────────────┐
                     ▼                                        ▼                         ▼
             PostgreSQL 16 (RLS)                    Transactional outbox ──► Celery workers / inline relay
             app role: aseo_app                     (outbox_events)            crawl · agents · executions
                     ▲                                                          verification · GSC sync
                     │                                                                 │
             Object storage (snapshots, reports)        SSRF-guarded egress ◄──────────┘
                                                       sites · WordPress · Shopify · GitHub · Google · Anthropic
```

## Backend modules (`apps/api/aseo`)

| Area | Module |
|---|---|
| auth, tenancy, workspaces, RBAC | `services/tenancy.py`, `services/rbac.py`, `api/deps.py` |
| sites & verification | `services/sites.py` |
| connectors | `connectors/{base,wordpress,shopify,github,public}.py`, `services/connectors.py`, `services/secrets.py` |
| crawler | `crawler/{urls,netguard,robots,parse,engine}.py`, `services/crawls.py` |
| SEO rules & scoring | `rules/engine.py` |
| AI gateway & agents | `ai/gateway.py`, `agents/{schemas,runtime,agents,workflows}.py` |
| change sets, policy, approvals, executions, rollback | `services/{changes,policy,validation,locks}.py` |
| schedules, events, outbox | `services/outbox.py`, `agents/workflows.py`, `worker/celery_app.py` |
| analytics & keywords | `services/gsc.py` |
| content, reporting | `api/routes/ops.py`, `services/reports.py` |
| billing | `services/{billing,payments}.py` |
| audit, notifications, retention | `services/{audit,notifications,retention}.py` |

## The fix workflow (state machine)

```
finding ─► proposal (Execution Agent drafts / user writes)
        ─► validation (deterministic)                         invalid
        ─► immutable patch version (sha256 hash)
        ─► policy evaluation ─┬─ deny ─────────────────────► blocked / recommendation
                              ├─ require_approval ─► pending_approval ─► approved | rejected
                              └─ auto_approve (Autopilot only) ─► approved
        ─► queued (outbox) ─► executing: re-check kill switch, approval binding, resource version, resource lock
        ─► connector write (rollback snapshot captured first)
        ─► verifying: re-read resource + fetch live HTML ─► completed | verifying (cache) | awaiting_deploy (PR)
                                                          └► verification_failed
        ─► rollback (where supported) ─► rolled_back | rollback_failed (needs human)
        ─► measurement (annotation + Measurement Agent)
```

Every transition writes an append-only, hash-chained audit event.

## Agents

Four logical agents (+ Copilot) run as typed steps of persisted `workflow_runs`. Each has a
bounded tool list (`agents/runtime.py:AGENT_TOOLS`); every tool call is recorded in
`tool_invocations`; every run records provider, model, prompt version, tokens, cost and credits.
Outputs are Pydantic-validated and every cited evidence ID must exist in the context the agent
was given, otherwise the output is rejected (one retry, then deterministic fallback).

| Agent | Produces | LLM? |
|---|---|---|
| Audit | issue clusters with explanations | optional |
| Strategy | prioritised plan, keyword opportunities, metadata drafts, content briefs | optional |
| Execution | immutable patches routed through validation/policy | never (deterministic) |
| Measurement | verified outcome + before/after GSC comparison with caveats | never (statistics) |
| Copilot | grounded answers with citations and proposed actions | optional |

## Background jobs

State changes and their side-effecting jobs are written in one transaction to `outbox_events`.
The relay claims due rows with `FOR UPDATE SKIP LOCKED`, runs the handler, then marks done,
retries with exponential backoff, or dead-letters after `max_attempts`. Handlers are idempotent
(executions check their status; crawls are deduplicated per site; ledger charges use idempotency
keys), so duplicate deliveries and worker restarts are safe.
