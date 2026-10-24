"""Distributed locks using PostgreSQL session-level advisory locks (works across API and
worker processes without extra infrastructure)."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

from sqlalchemy import text

from aseo.core.db import get_engine
from aseo.core.errors import Conflict


@contextlib.contextmanager
def resource_lock(key: str) -> Iterator[None]:
    engine = get_engine()
    with engine.connect() as conn:
        got = conn.execute(text("select pg_try_advisory_lock(hashtextextended(:k, 0))"), {"k": key}).scalar()
        conn.commit()
        if not got:
            raise Conflict("Another operation is in progress on this resource.", code="resource_locked")
        try:
            yield
        finally:
            conn.execute(text("select pg_advisory_unlock(hashtextextended(:k, 0))"), {"k": key})
            conn.commit()
