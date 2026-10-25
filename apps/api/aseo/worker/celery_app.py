"""Celery worker for TASK_EXECUTION=celery.

The worker does not receive job payloads directly: the transactional outbox is the source of
truth. ``aseo.relay`` claims due outbox rows (FOR UPDATE SKIP LOCKED) and runs their
handlers, so a worker crash or restart simply leaves rows to be re-claimed after their lock
expires (at-least-once with idempotent handlers). Beat triggers the relay every few seconds
and the scheduler every minute.
"""

from __future__ import annotations

from celery import Celery

from aseo.core.config import get_settings
from aseo.core.logging import configure_logging

settings = get_settings()
celery_app = Celery("lodestar", broker=settings.redis_url, backend=None)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=900,
    task_soft_time_limit=840,
    beat_schedule={
        "relay": {"task": "aseo.relay", "schedule": 3.0},
        "scheduler": {"task": "aseo.scheduler", "schedule": 60.0},
    },
)


@celery_app.on_after_configure.connect
def _setup(**_: object) -> None:
    configure_logging()


def _register_handlers() -> None:
    import aseo.agents.workflows  # noqa: F401
    import aseo.api.routes.changes  # noqa: F401 — agents.plan handler
    import aseo.services.changes  # noqa: F401
    import aseo.services.crawls  # noqa: F401
    import aseo.services.gsc  # noqa: F401


@celery_app.task(name="aseo.relay")
def relay_task() -> int:
    _register_handlers()
    from aseo.services import outbox

    return outbox.drain(limit=20, max_rounds=10)


@celery_app.task(name="aseo.scheduler")
def scheduler_task() -> int:
    _register_handlers()
    from aseo.agents.workflows import scheduler_tick

    return scheduler_tick()
