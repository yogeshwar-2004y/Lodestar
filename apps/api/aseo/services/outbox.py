"""Transactional outbox + job relay.

State changes and the jobs they trigger are written in one transaction (``enqueue``).
The relay claims due events with ``FOR UPDATE SKIP LOCKED``, runs the registered handler,
and records success, retry with exponential backoff, or dead-letter after ``max_attempts``.

In ``TASK_EXECUTION=celery`` mode the relay runs inside Celery workers (beat triggers
``aseo.relay`` every few seconds); in ``inline`` mode the API drains the outbox on a
background thread after each request that enqueued work.
"""

from __future__ import annotations

import logging
import threading
import traceback
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aseo.core.config import get_settings
from aseo.core.db import system_session
from aseo.models import OutboxEvent
from aseo.models.base import utcnow

log = logging.getLogger("aseo.outbox")

Handler = Callable[[dict[str, Any], uuid.UUID | None], None]
_HANDLERS: dict[str, Handler] = {}


class RetryableJobError(Exception):
    pass


class PermanentJobError(Exception):
    pass


def handler(topic: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _HANDLERS[topic] = fn
        return fn

    return deco


def enqueue(
    db: Session,
    topic: str,
    payload: dict[str, Any],
    *,
    tenant_id: uuid.UUID | None,
    dedupe_key: str | None = None,
    delay_seconds: float = 0,
    max_attempts: int = 5,
) -> OutboxEvent | None:
    """Insert an outbox event in the caller's transaction. Returns None if an event with the
    same dedupe key already exists (duplicate job suppression)."""
    if dedupe_key:
        existing = db.execute(select(OutboxEvent).where(OutboxEvent.dedupe_key == dedupe_key)).scalar_one_or_none()
        if existing is not None:
            return None
    ev = OutboxEvent(
        tenant_id=tenant_id,
        topic=topic,
        payload=payload,
        dedupe_key=dedupe_key,
        available_at=utcnow() + timedelta(seconds=delay_seconds),
        max_attempts=max_attempts,
    )
    try:
        with db.begin_nested():
            db.add(ev)
            db.flush()
    except IntegrityError:
        return None
    db.info.setdefault("outbox_enqueued", True)
    return ev


def _claim(limit: int) -> list[uuid.UUID]:
    with system_session() as db:
        now = utcnow()
        rows = (
            db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.status.in_(["pending", "processing"]),
                    OutboxEvent.available_at <= now,
                    or_(OutboxEvent.locked_until.is_(None), OutboxEvent.locked_until < now),
                )
                .order_by(OutboxEvent.available_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        for ev in rows:
            ev.status = "processing"
            ev.locked_until = now + timedelta(minutes=10)
            ev.attempts += 1
        return [ev.id for ev in rows]


def process_event(event_id: uuid.UUID) -> str:
    with system_session() as db:
        ev = db.get(OutboxEvent, event_id)
        if ev is None or ev.status in ("done", "dead"):
            return "skipped"
        topic, payload, tenant_id, attempts, max_attempts = ev.topic, dict(ev.payload), ev.tenant_id, ev.attempts, ev.max_attempts
    fn = _HANDLERS.get(topic)
    status, error = "done", None
    try:
        if fn is None:
            raise PermanentJobError(f"no handler for topic {topic}")
        fn(payload, tenant_id)
    except PermanentJobError as exc:
        status, error = "dead", str(exc)
    except Exception as exc:  # noqa: BLE001 — every failure is recorded
        error = f"{type(exc).__name__}: {exc}"
        status = "dead" if attempts >= max_attempts else "retry"
        log.warning("job failed", extra={"job": topic, "status": status})
        log.debug(traceback.format_exc())
    with system_session() as db:
        ev = db.get(OutboxEvent, event_id)
        assert ev is not None
        ev.last_error = error
        ev.locked_until = None
        if status == "retry":
            ev.status = "pending"
            base = get_settings().outbox_retry_base_seconds
            ev.available_at = utcnow() + timedelta(seconds=min(300, base * 2 ** ev.attempts))
        else:
            ev.status = status
            ev.finished_at = utcnow()
    return status


def drain(limit: int = 50, max_rounds: int = 200) -> int:
    """Process due events until none remain (used by inline mode and tests)."""
    processed = 0
    for _ in range(max_rounds):
        ids = _claim(limit)
        if not ids:
            break
        for event_id in ids:
            process_event(event_id)
            processed += 1
    return processed


_drain_lock = threading.Lock()


def kick() -> None:
    """Trigger dispatch after a commit. Inline mode drains on a background thread;
    celery mode sends the relay task."""
    settings = get_settings()
    if settings.task_execution == "manual":
        return
    if settings.task_execution == "celery":
        try:
            from aseo.worker.celery_app import celery_app

            celery_app.send_task("aseo.relay")
        except Exception:  # noqa: BLE001 — beat will pick it up anyway
            log.warning("could not signal relay; beat will retry")
        return

    def _run() -> None:
        if not _drain_lock.acquire(blocking=False):
            return
        try:
            drain()
        finally:
            _drain_lock.release()

    threading.Thread(target=_run, daemon=True).start()
