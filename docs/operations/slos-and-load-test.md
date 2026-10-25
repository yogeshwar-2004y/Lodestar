# Pilot SLOs and load-test results

## Proposed pilot SLOs (targets to measure against, not guarantees)

| SLO | Target | Measured by |
|---|---|---|
| API availability (non-5xx) | 99.5% monthly | ALB metrics |
| Read API latency | p95 < 500 ms | request logs (`duration_ms`) |
| Approved change → write attempted | p95 < 2 min | `execution_runs.started_at - created_at` |
| Write → verification result (direct connectors) | p95 < 5 min | `execution_runs.finished_at - started_at` |
| Crawl of 200 pages | p95 < 10 min | `crawl_jobs` |
| Zero unapproved writes | 100% | audit log: every `execution.write_applied` has an approval (manual or policy auto-approval) |

## Local load test (measured 2026-10-25)

`scripts/loadtest.py --requests 1500 --concurrency 20` against one API process (uvicorn, no
`--workers`), local PostgreSQL 16, Apple M2 laptop, demo dataset, rate limit raised for the test:

| Endpoint | p50 ms | p95 ms | p99 ms |
|---|---|---|---|
| `/sites/{id}/overview` | 78.6 | 438.3 | 773.3 |
| `/sites/{id}/findings` | 63.1 | 394.6 | 695.9 |
| `/sites/{id}/pages` | 63.1 | 410.0 | 649.4 |
| `/change-sets` | 60.1 | 387.9 | 617.6 |
| `/sites/{id}/performance` | 79.7 | 431.1 | 785.4 |

Throughput 163 req/s, 0 errors. With the default rate limit (240 req/min per IP) the same test
correctly returned 429 for most requests. These numbers reflect a small dataset on a laptop; repeat
the test on pilot infrastructure with realistic data before committing to SLOs. Scaling levers:
multiple uvicorn workers/tasks, a read replica, and caching of `overview`.
