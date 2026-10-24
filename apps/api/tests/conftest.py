"""Test harness.

* Migrates a fresh ``aseo_test`` database as the owner role, then runs the API as the
  non-superuser ``aseo_app`` role so PostgreSQL RLS is actually enforced in tests.
* Starts the WordPress fixture server (Lodestar companion contract) on a free port.
* Background work is drained deterministically with ``outbox.drain()``.
"""

from __future__ import annotations

import importlib.util
import os
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
OWNER_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://localhost:5432/aseo_test")
APP_URL = os.environ.get("TEST_DATABASE_APP_URL", "postgresql+psycopg://aseo_app:aseo_app_dev_password@localhost:5432/aseo_test")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


WP_PORT = _free_port()
os.environ.update({
    "ENVIRONMENT": "test",
    "DEMO_MODE": "true",
    "DATABASE_URL": OWNER_URL,
    "DATABASE_APP_URL": APP_URL,
    "TASK_EXECUTION": "manual",
    "OUTBOX_RETRY_BASE_SECONDS": "0",
    "AI_PROVIDER": "deterministic",
    "CRAWLER_ALLOWED_PRIVATE_HOSTS": f'["127.0.0.1:{WP_PORT}"]',
    "CRAWLER_DEFAULT_DELAY_SECONDS": "0",
    "SNAPSHOT_DIR": str(ROOT / "apps/api/var/test-snapshots"),
    "RATE_LIMIT_PER_MINUTE": "100000",
    "AUTH_RATE_LIMIT_PER_MINUTE": "100000",
    "REDIS_URL": "redis://127.0.0.1:1/0",  # force in-memory limiter in tests
})


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    eng = create_engine(OWNER_URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO aseo_app"))
    eng.dispose()
    cfg = Config(str(ROOT / "apps/api/alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "apps/api/migrations"))
    cfg.attributes["database_url"] = OWNER_URL
    command.upgrade(cfg, "head")


def _start_wp_fixture() -> object:
    import uvicorn

    path = ROOT / "integrations/wordpress/fixture_server/server.py"
    spec = importlib.util.spec_from_file_location("wp_fixture_server", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wp_fixture_server"] = mod
    spec.loader.exec_module(mod)
    server = uvicorn.Server(uvicorn.Config(mod.app, host="127.0.0.1", port=WP_PORT, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", WP_PORT), timeout=0.1).close()
            break
        except OSError:
            time.sleep(0.05)
    return mod


@pytest.fixture(scope="session", autouse=True)
def _session_setup():
    _migrate()
    from aseo.core.config import get_settings
    from aseo.core.db import reset_engine

    get_settings.cache_clear()
    reset_engine()
    yield


@pytest.fixture(scope="session")
def wp():
    mod = _start_wp_fixture()

    class WP:
        base = f"http://127.0.0.1:{WP_PORT}"
        module = mod

        def reset(self) -> None:
            mod.reset()

        def set_token(self, token: str) -> None:
            mod.STATE["token"] = token

        def post(self, post_id: int) -> dict:
            return mod.STATE["posts"][post_id]

        def faults(self, status: int | None, count: int) -> None:
            mod.STATE["faults"] = {"status": status, "count": count, "delay": 0.0}

    return WP()


@pytest.fixture(scope="session")
def app():
    from aseo.api.app import create_app

    return create_app(start_background=False)


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


class Api:
    """Small helper around TestClient using bearer auth (as an API client would)."""

    def __init__(self, client, token: str):
        self.c = client
        self.h = {"Authorization": f"Bearer {token}"}

    def get(self, path, **kw):
        return self.c.get(f"/api/v1{path}", headers=self.h, **kw)

    def post(self, path, json=None, headers=None, **kw):
        return self.c.post(f"/api/v1{path}", json=json, headers={**self.h, **(headers or {})}, **kw)

    def put(self, path, json=None):
        return self.c.put(f"/api/v1{path}", json=json, headers=self.h)

    def patch(self, path, json=None):
        return self.c.patch(f"/api/v1{path}", json=json, headers=self.h)

    def delete(self, path):
        return self.c.delete(f"/api/v1{path}", headers=self.h)


@pytest.fixture()
def make_user(client):
    def _make(org: str | None = "Acme", kind: str = "business") -> Api:
        email = f"u{uuid.uuid4().hex[:10]}@example.com"
        r = client.post("/api/v1/auth/register", json={"email": email, "name": "Test User", "password": "correct horse battery",
                                                       "organization_name": org, "organization_kind": kind})
        assert r.status_code == 201, r.text
        api = Api(client, r.json()["token"])
        api.email = email
        api.session = r.json()
        return api

    return _make


def drain() -> int:
    from aseo.services import outbox

    return outbox.drain()


@pytest.fixture()
def wp_site(make_user, wp):
    """A verified WordPress (fixture) site with a connected connector and a completed crawl."""
    wp.reset()
    api = make_user()
    r = api.post("/sites", {"name": "Northwind Coffee", "url": wp.base, "platform": "wordpress"})
    assert r.status_code == 201, r.text
    site = r.json()
    r = api.post(f"/sites/{site['id']}/connectors", {"provider": "wordpress", "mode": "fixture",
                                                     "config": {"username": "lodestar-agent"},
                                                     "secrets": {"app_password": "fixture-app-password"}})
    assert r.status_code == 201 and r.json()["status"] == "connected", r.text
    r = api.post(f"/sites/{site['id']}/verification/start", {"method": "connector"})
    wp.set_token(r.json()["token"])
    r = api.post(f"/sites/{site['id']}/verification/check")
    assert r.json()["status"] == "verified", r.text
    r = api.post(f"/sites/{site['id']}/crawls", {})
    assert r.status_code == 202, r.text
    drain()
    crawl = api.get(f"/crawls/{r.json()['id']}").json()
    assert crawl["status"] == "completed", crawl
    return api, site
