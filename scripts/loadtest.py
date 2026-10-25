"""Small read-path load test against a running local stack (`make dev` + `make seed`).

Usage: apps/api/.venv/bin/python scripts/loadtest.py [--requests 1500] [--concurrency 20]
Reports throughput and latency percentiles per endpoint. Results depend on hardware; they
are measurements of this environment, not guarantees.
"""

import argparse
import asyncio
import statistics
import time

import httpx

BASE = "http://127.0.0.1:8400/api/v1"


async def main(total: int, concurrency: int) -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{BASE}/auth/login", json={"email": "demo@lodestar.example", "password": "demo-password-123"})
        r.raise_for_status()
        h = {"Authorization": f"Bearer {r.json()['token']}"}
        site = (await c.get(f"{BASE}/sites", headers=h)).json()[0]["id"]
        paths = [f"/sites/{site}/overview", f"/sites/{site}/findings", f"/sites/{site}/pages?limit=50", "/change-sets?limit=25",
                 f"/sites/{site}/performance?days=90"]
        lat: dict[str, list[float]] = {p.split("?")[0].replace(site, "{id}"): [] for p in paths}
        errors = 0
        sem = asyncio.Semaphore(concurrency)

        async def one(i: int) -> None:
            nonlocal errors
            p = paths[i % len(paths)]
            async with sem:
                t = time.perf_counter()
                resp = await c.get(BASE + p, headers=h)
                lat[p.split("?")[0].replace(site, "{id}")].append((time.perf_counter() - t) * 1000)
                errors += resp.status_code != 200

        t0 = time.perf_counter()
        await asyncio.gather(*(one(i) for i in range(total)))
        dt = time.perf_counter() - t0
    print(f"{total} requests, concurrency {concurrency}: {total / dt:.0f} req/s, errors {errors}")
    print(f"{'endpoint':42} {'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8}")
    for k, v in lat.items():
        v.sort()
        print(f"{k:42} {statistics.median(v):8.1f} {v[int(len(v) * .95) - 1]:8.1f} {v[int(len(v) * .99) - 1]:8.1f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", type=int, default=1500)
    ap.add_argument("--concurrency", type=int, default=20)
    a = ap.parse_args()
    asyncio.run(main(a.requests, a.concurrency))
